"""The polling loop: `python -m scheduler`.

claim due sources -> fetch -> extract -> record -> alert, forever. Claims are
leased in the DB (see db.claim_due_sources), so running more than one
scheduler machine is safe.
"""

import asyncio
import logging
import random
import signal
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

from config import SCHEDULER_REQUIRED, ConfigError, Settings, load_settings
from db import Database, SourceRow
from extract import base as extract_base
from extract import learned
from extract.base import Extracted
from extract.meta import page_meta
from fetcher import Fetcher, FetchResult, domain_of
from logs import setup_logging, warn_once
from models import PricePoint
from notify import EmailSender, ResendSender, dispatch_alerts

log = logging.getLogger("scheduler")

# last_error copy: says what happened in plain words; the app shows it.
NO_PRICE = "The page loaded but no price was found; the layout probably changed."
BLOCKED = "The retailer blocked the request (bot protection)."
BAD_PRICE = "The page loaded but the price we read wasn't a valid amount, so we didn't save it."
CRASHED = "Reading the page failed unexpectedly. We'll try again on the next check."
NOT_BUILT = "Not checked yet: automatic price reading for this site isn't built. We'll keep trying."

HEARTBEAT = timedelta(hours=24)
INTERVAL_JITTER = 0.1   # next check lands within ±10% of check_interval_mins


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> FetchResult: ...


def should_record(latest: PricePoint | None, new: PricePoint) -> bool:
    """Delta logging: write on any change, or as a heartbeat after 24h.

    The heartbeat keeps row-based medians/percentiles in my_watchlist roughly
    time-weighted, and gives evaluate() at least one point per day.
    """
    if latest is None:
        return True
    if (latest.price_cents, latest.in_stock, latest.currency) != (
        new.price_cents, new.in_stock, new.currency
    ):
        return True
    return new.observed_at - latest.observed_at > HEARTBEAT


def next_check_at(now: datetime, interval_mins: int, rng: random.Random | None = None) -> datetime:
    r = (rng or random).uniform(1 - INTERVAL_JITTER, 1 + INTERVAL_JITTER)
    return now + timedelta(minutes=max(1, interval_mins) * r)


def fetch_failure_message(result: FetchResult) -> str:
    if result.kind == "blocked":
        return BLOCKED
    if result.kind == "http_error":
        return f"The retailer's page returned an error ({result.error}). The link may have changed."
    return f"The page couldn't be reached ({result.error}). We'll try again on the next check."


def run_extractor(source: SourceRow, html: str) -> list[Extracted]:
    """Learned path when the user taught one, else the registry. May raise NotImplementedError."""
    if source.extractor_config.get("learned") is True:
        return learned.resolve(html, source.extractor_config)
    return extract_base.extract(html, source.canonical_url)


def is_valid(e: Any) -> bool:
    """Integer cents and a real stock flag; anything else is not a price we save."""
    return (
        isinstance(e, Extracted)
        and type(e.price_cents) is int
        and e.price_cents > 0
        and type(e.in_stock) is bool
        and isinstance(e.currency, str) and len(e.currency.strip()) == 3
        and (e.variant_key is None or isinstance(e.variant_key, str))
    )


def interleave_by_domain(sources: list[SourceRow]) -> list[SourceRow]:
    """Round-robin across domains so one busy retailer doesn't hog every slot
    while its requests wait on the per-domain lock."""
    queues: dict[str, deque[SourceRow]] = defaultdict(deque)
    for s in sources:
        queues[domain_of(s.canonical_url)].append(s)
    out: list[SourceRow] = []
    while queues:
        for d in list(queues):
            out.append(queues[d].popleft())
            if not queues[d]:
                del queues[d]
    return out


@dataclass
class Worker:
    db: Database
    fetcher: PageFetcher
    sender: EmailSender
    settings: Settings
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    async def process_source(self, source: SourceRow) -> str:
        """Check one source. Returns an outcome label (for logs and tests)."""
        if source.status not in ("active", "failing"):
            return "skipped"

        result = await self.fetcher.fetch(source.canonical_url)
        now = self.clock()
        nxt = next_check_at(now, source.check_interval_mins)
        if not result.ok:
            return await self._fail(source, fetch_failure_message(result), nxt)

        try:
            # Parsing a 1 MB page takes a while; keep the loop free for other fetches.
            found = await asyncio.to_thread(run_extractor, source, result.html)
        except NotImplementedError:
            warn_once(log, "extract.extract",
                      "extract.base.extract() is not implemented yet; sources without a "
                      "learned path are rescheduled without counting a failure.")
            async with self.db.transaction() as q:
                await q.record_skipped(source.id, NOT_BUILT, nxt)
            return "not_implemented"
        except Exception:
            log.exception("extractor crashed on source %s", source.id)
            return await self._fail(source, CRASHED, nxt)

        if not found:
            return await self._fail(source, NO_PRICE, nxt)
        valid: dict[str, Extracted] = {}
        for e in found:
            if not is_valid(e):
                log.error("source %s: dropping invalid extraction %r", source.id, e)
                continue
            valid.setdefault(e.variant_key or "", e)   # first wins on duplicate keys
        if not valid:
            return await self._fail(source, BAD_PRICE, nxt)

        title = image = None
        if source.title is None or source.image_url is None:
            meta = await asyncio.to_thread(page_meta, result.html, result.url)
            title, image = meta.title, meta.image_url

        written: list[tuple[str, str, PricePoint]] = []
        async with self.db.transaction() as q:
            for key, e in valid.items():
                vid = await q.upsert_variant(source.id, key)
                point = PricePoint(now, e.price_cents, e.in_stock, e.currency.strip().upper())
                if should_record(await q.latest_point(vid), point):
                    await q.insert_price_point(vid, point)
                    written.append((vid, key, point))
            await q.record_success(source.id, nxt, title=title, image_url=image)

        for vid, key, point in written:
            try:
                await dispatch_alerts(self.db, self.sender, app_url=self.settings.app_url,
                                      source=source, variant_id=vid, variant_key=key, latest=point)
            except Exception:
                log.exception("alert dispatch failed for source %s variant %s", source.id, key)
        log.info("source %s: %d variant(s), %d point(s) written", source.id, len(valid), len(written))
        return "ok"

    async def _fail(self, source: SourceRow, message: str, nxt: datetime) -> str:
        async with self.db.transaction() as q:
            failures, status = await q.record_failure(source.id, message, nxt)
        log.info("source %s failed (%d in a row, %s): %s", source.id, failures, status, message)
        return "failed"

    async def run_once(self) -> int:
        """Claim one batch and process it. Returns how many sources were claimed."""
        async with self.db.transaction() as q:
            batch = await q.claim_due_sources(self.settings.batch_size, self.settings.lease_mins)
        if not batch:
            return 0
        slots = asyncio.Semaphore(self.settings.concurrency)

        async def one(s: SourceRow) -> None:
            async with slots:
                try:
                    await self.process_source(s)
                except Exception:
                    # Most likely the DB; the lease expires and the source is retried.
                    log.exception("checking source %s failed", s.id)

        await asyncio.gather(*(one(s) for s in interleave_by_domain(batch)))
        return len(batch)

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                claimed = await self.run_once()
            except Exception:
                log.exception("poll failed")
                claimed = 0
            if claimed:
                continue
            idle = self.settings.idle_sleep_s * random.uniform(0.5, 1.5)
            try:
                await asyncio.wait_for(stop.wait(), timeout=idle)
            except TimeoutError:
                pass


async def amain(settings: Settings) -> None:
    db = Database(settings.database_url, settings.db_pool_size)
    fetcher = Fetcher(min_delay_s=settings.domain_delay_s, jitter_s=settings.domain_jitter_s,
                      timeout_s=settings.fetch_timeout_s)
    sender = ResendSender(settings.resend_api_key, settings.alert_from_email)
    worker = Worker(db, fetcher, sender, settings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("scheduler started (batch %d, concurrency %d)", settings.batch_size, settings.concurrency)
    try:
        await worker.run_forever(stop)
    finally:
        await fetcher.aclose()
        await db.close()
        log.info("scheduler stopped")


def main() -> None:
    setup_logging()
    try:
        settings = load_settings(SCHEDULER_REQUIRED)
    except ConfigError as e:
        raise SystemExit(f"scheduler: {e}") from e
    asyncio.run(amain(settings))


if __name__ == "__main__":
    main()
