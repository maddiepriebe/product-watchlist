"""Postgres access for the scheduler.

DATABASE_URL is the service connection: it bypasses RLS, so only the worker
holds it. Every query lives on Queries, which is bound to one connection
inside one transaction; Database hands those out from a tiny pool (the
approved deps don't include psycopg_pool, and a few long-lived connections
are all one scheduler needs).
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, AsyncIterator

import psycopg
from psycopg.rows import dict_row

from models import AlertReason, PricePoint, SentAlert, Watch

log = logging.getLogger(__name__)

FAILING_AFTER = 3   # consecutive failures before a source shows as failing


@dataclass(frozen=True)
class SourceRow:
    id: str
    canonical_url: str
    retailer: str
    title: str | None
    image_url: str | None
    extractor: str
    extractor_config: dict[str, Any]
    status: str
    check_interval_mins: int
    consecutive_failures: int


@dataclass(frozen=True)
class WatchRow:
    """A watch linked to a source, plus what dispatch needs beyond models.Watch."""

    id: str
    user_id: str
    nickname: str | None
    channel: str
    watched_variant_keys: list[str] | None
    alert_below_cents: int | None
    alert_pct_drop: Any   # Decimal from numeric(5,2)
    alert_on_new_low: bool
    alert_on_restock: bool
    muted_until: datetime | None
    min_alert_gap_hrs: int

    def to_model(self, recent_alerts: tuple[SentAlert, ...]) -> Watch:
        return Watch(
            id=self.id,
            alert_below_cents=self.alert_below_cents,
            alert_pct_drop=self.alert_pct_drop,
            alert_on_new_low=self.alert_on_new_low,
            alert_on_restock=self.alert_on_restock,
            muted_until=self.muted_until,
            min_alert_gap_hrs=self.min_alert_gap_hrs,
            recent_alerts=recent_alerts,
        )


def split_variant_key(variant_key: str | None) -> tuple[str, str | None, str | None]:
    """None/"" -> ("", None, None); "M|black" -> ("M|black", "M", "black")."""
    key = variant_key or ""
    if not key:
        return "", None, None
    size, _, color = key.partition("|")
    return key, (size.strip() or None), (color.strip() or None)


def _point(row: dict[str, Any]) -> PricePoint:
    return PricePoint(
        observed_at=row["observed_at"],
        price_cents=row["price_cents"],
        in_stock=row["in_stock"],
        currency=row["currency"].strip(),   # char(3)
    )


class Queries:
    def __init__(self, conn: psycopg.AsyncConnection[dict[str, Any]]) -> None:
        self.conn = conn

    async def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = await self.conn.execute(sql, params)
        return await cur.fetchall()

    async def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        cur = await self.conn.execute(sql, params)
        return await cur.fetchone()

    # -------------------------------------------------------------- queue

    async def claim_due_sources(self, limit: int, lease_mins: int) -> list[SourceRow]:
        """Claim up to `limit` due sources.

        SKIP LOCKED lets parallel workers claim disjoint rows, and pushing
        next_check_at forward is the lease: once this commits, the rows
        aren't due for anyone else until the lease runs out. A worker that
        dies mid-check just lets the lease expire and the source is retried.
        """
        rows = await self._all(
            """
            with due as (
              select id from product_sources
               where status in ('active', 'failing') and next_check_at <= now()
               order by next_check_at
               limit %s
               for update skip locked
            )
            update product_sources s
               set next_check_at = now() + make_interval(mins => %s)
              from due
             where s.id = due.id
            returning s.id::text, s.canonical_url, s.retailer, s.title, s.image_url,
                      s.extractor::text, s.extractor_config, s.status::text,
                      s.check_interval_mins, s.consecutive_failures
            """,
            (limit, lease_mins),
        )
        return [SourceRow(**r) for r in rows]

    async def record_success(
        self, source_id: str, next_check_at: datetime,
        title: str | None = None, image_url: str | None = None,
    ) -> None:
        # Only failing flips back to active: a user may have paused the
        # source while we were fetching it. Title/image fill in only if empty.
        await self.conn.execute(
            """
            update product_sources
               set status = case when status = 'failing' then 'active'::source_status
                                 else status end,
                   consecutive_failures = 0,
                   last_error = null,
                   last_checked_at = now(),
                   next_check_at = %s,
                   title = coalesce(title, %s),
                   image_url = coalesce(image_url, %s)
             where id = %s
            """,
            (next_check_at, title, image_url, source_id),
        )

    async def record_failure(
        self, source_id: str, error: str, next_check_at: datetime
    ) -> tuple[int, str]:
        row = await self._one(
            """
            update product_sources
               set consecutive_failures = consecutive_failures + 1,
                   status = case when status = 'active'
                                  and consecutive_failures + 1 >= %s
                                 then 'failing'::source_status
                                 else status end,
                   last_error = %s,
                   last_checked_at = now(),
                   next_check_at = %s
             where id = %s
            returning consecutive_failures, status::text
            """,
            (FAILING_AFTER, error, next_check_at, source_id),
        )
        assert row is not None, f"source {source_id} vanished"
        return row["consecutive_failures"], row["status"]

    async def record_skipped(self, source_id: str, note: str, next_check_at: datetime) -> None:
        """A check that couldn't run for reasons that aren't the source's fault."""
        await self.conn.execute(
            """
            update product_sources
               set last_error = %s, last_checked_at = now(), next_check_at = %s
             where id = %s
            """,
            (note, next_check_at, source_id),
        )

    # ---------------------------------------------------------- variants

    async def upsert_variant(self, source_id: str, variant_key: str | None) -> str:
        key, size, color = split_variant_key(variant_key)
        row = await self._one(
            """
            insert into variants (source_id, variant_key, size, color)
            values (%s, %s, %s, %s)
            on conflict (source_id, variant_key)
              do update set size = excluded.size, color = excluded.color
            returning id::text
            """,
            (source_id, key, size, color),
        )
        assert row is not None
        return row["id"]

    async def latest_point(self, variant_id: str) -> PricePoint | None:
        row = await self._one(
            """
            select observed_at, price_cents, in_stock, currency
              from price_points where variant_id = %s
             order by observed_at desc limit 1
            """,
            (variant_id,),
        )
        return _point(row) if row else None

    async def insert_price_point(self, variant_id: str, point: PricePoint) -> None:
        await self.conn.execute(
            """
            insert into price_points (variant_id, observed_at, price_cents, currency, in_stock)
            values (%s, %s, %s, %s, %s)
            """,
            (variant_id, point.observed_at, point.price_cents, point.currency, point.in_stock),
        )

    async def history(self, variant_id: str, before: datetime, days: int = 91) -> list[PricePoint]:
        """Points strictly before `before`, oldest first.

        91 days rather than 90: the heartbeat guarantees a point at least
        daily, so the extra day includes the price in effect when the 90-day
        window opened.
        """
        rows = await self._all(
            """
            select observed_at, price_cents, in_stock, currency
              from price_points
             where variant_id = %s and observed_at < %s and observed_at >= %s
             order by observed_at asc
            """,
            (variant_id, before, before - timedelta(days=days)),
        )
        return [_point(r) for r in rows]

    # ------------------------------------------------------------ alerts

    async def watches_for_variant(self, source_id: str, variant_key: str) -> list[WatchRow]:
        rows = await self._all(
            """
            select w.id::text, w.user_id::text, w.nickname, w.channel::text,
                   w.watched_variant_keys, w.alert_below_cents, w.alert_pct_drop,
                   w.alert_on_new_low, w.alert_on_restock, w.muted_until,
                   w.min_alert_gap_hrs
              from watches w
              join watch_sources ws on ws.watch_id = w.id
             where ws.source_id = %s
               and w.archived_at is null
               and (w.watched_variant_keys is null or %s = any (w.watched_variant_keys))
             order by w.created_at
            """,
            (source_id, variant_key),
        )
        return [WatchRow(**r) for r in rows]

    async def recent_alerts(self, watch_id: str, since: datetime) -> tuple[SentAlert, ...]:
        """Delivered alerts, newest first. Failed sends don't count as sent."""
        rows = await self._all(
            """
            select sent_at, reason::text, price_cents
              from notifications
             where watch_id = %s and delivered and sent_at >= %s
             order by sent_at desc
            """,
            (watch_id, since),
        )
        return tuple(SentAlert(r["sent_at"], r["reason"], r["price_cents"]) for r in rows)

    async def insert_notification(
        self, *, watch_id: str, source_id: str, variant_id: str,
        reason: AlertReason, price_cents: int, sent_at: datetime,
    ) -> int:
        row = await self._one(
            """
            insert into notifications (watch_id, source_id, variant_id, reason, price_cents, sent_at)
            values (%s, %s, %s, %s::alert_reason, %s, %s)
            returning id
            """,
            (watch_id, source_id, variant_id, reason, price_cents, sent_at),
        )
        assert row is not None
        return row["id"]

    async def mark_notification(self, notification_id: int, *, delivered: bool, error: str | None) -> None:
        await self.conn.execute(
            "update notifications set delivered = %s, error = %s where id = %s",
            (delivered, error, notification_id),
        )

    async def user_email(self, user_id: str) -> str | None:
        row = await self._one("select email from auth.users where id = %s", (user_id,))
        return row["email"] if row else None


class Database:
    def __init__(self, url: str, size: int = 4) -> None:
        self._url = url
        # None slots connect lazily, and replace connections that broke.
        self._slots: asyncio.Queue[psycopg.AsyncConnection[dict[str, Any]] | None] = asyncio.Queue()
        for _ in range(size):
            self._slots.put_nowait(None)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        # prepare_threshold=None: safe behind Supabase's pooler (pgbouncer
        # can't track server-side prepared statements across backends).
        return await psycopg.AsyncConnection.connect(
            self._url, autocommit=True, row_factory=dict_row, prepare_threshold=None
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Queries]:
        conn = await self._slots.get()
        try:
            if conn is None or conn.closed:
                conn = await self._connect()
            async with conn.transaction():
                yield Queries(conn)
        finally:
            if conn is not None and (conn.closed or conn.broken):
                conn = None
            self._slots.put_nowait(conn)

    async def close(self) -> None:
        while not self._slots.empty():
            conn = self._slots.get_nowait()
            if conn is not None:
                await conn.close()

