import asyncio
import json
import logging
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import alerts
from config import Settings
from db import Database
from extract import base as extract_base
from extract.base import Extracted
from fetcher import FetchResult
from logs import reset_warn_once
from models import PricePoint
from scheduler import (
    BLOCKED, NO_PRICE, NOT_BUILT, Worker, interleave_by_domain, next_check_at, should_record,
)
from tests.fakes import FakeDB, FakeSender, make_source, make_watch
from tests.pgtest import database, db_url, requires_db, seed_source, sql  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures"
FARMRIO_HTML = (FIXTURES / "fixture-farmrio-com-products-rustic-flowers-winter-white-sleeveless-.html").read_text()
LEARNED_FARMRIO = {"learned": True, "blob": "jsonld", "block": 1, "path": ["offers", 0, "price"], "unit": "major"}
T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_warn_once()


class FakeFetcher:
    def __init__(self, *results: FetchResult) -> None:
        self.results = list(results)
        self.urls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.urls.append(url)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def ok(html: str = "<html></html>") -> FetchResult:
    return FetchResult("ok", "https://farmrio.com/products/rustic", 200, html)


class Clock:
    def __init__(self, t: datetime = T0) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def make_worker(fetcher: FakeFetcher, db: FakeDB | None = None, clock: Clock | None = None) -> Worker:
    return Worker(db or FakeDB(), fetcher, FakeSender(), Settings(app_url="https://app.test"),
                  clock=clock or Clock())


def patch_extract(monkeypatch: pytest.MonkeyPatch, *results: list[Extracted]) -> list[int]:
    calls: list[int] = []
    seq = list(results)

    def fake(html: str, url: str) -> list[Extracted]:
        calls.append(1)
        return seq.pop(0) if len(seq) > 1 else seq[0]

    monkeypatch.setattr(extract_base, "extract", fake)
    return calls


def ex(cents: int, in_stock: bool = True, key: str | None = None) -> Extracted:
    return Extracted(cents, "USD", in_stock, key, "jsonld")


# ---------------------------------------------------------------- pure rules

@pytest.mark.parametrize(
    "latest, new, expected",
    [
        (None, PricePoint(T0, 100, True), True),
        (PricePoint(T0, 100, True), PricePoint(T0 + timedelta(hours=23), 100, True), False),
        (PricePoint(T0, 100, True), PricePoint(T0 + timedelta(hours=24), 100, True), False),
        (PricePoint(T0, 100, True), PricePoint(T0 + timedelta(hours=24, seconds=1), 100, True), True),
        (PricePoint(T0, 100, True), PricePoint(T0 + timedelta(minutes=1), 99, True), True),
        (PricePoint(T0, 100, True), PricePoint(T0 + timedelta(minutes=1), 100, False), True),
        (PricePoint(T0, 100, True, "USD"), PricePoint(T0 + timedelta(minutes=1), 100, True, "CAD"), True),
    ],
)
def test_should_record(latest: PricePoint | None, new: PricePoint, expected: bool) -> None:
    assert should_record(latest, new) is expected


def test_next_check_is_jittered_around_interval() -> None:
    rng = random.Random(1)
    gaps = [(next_check_at(T0, 360, rng) - T0).total_seconds() / 60 for _ in range(200)]
    assert all(324 <= g <= 396 for g in gaps)
    assert len({round(g) for g in gaps}) > 10


def test_interleave_by_domain() -> None:
    srcs = [make_source(id=f"a{i}", canonical_url=f"https://a.com/{i}") for i in range(3)]
    srcs += [make_source(id="b0", canonical_url="https://www.b.com/0")]
    assert [s.id for s in interleave_by_domain(srcs)] == ["a0", "b0", "a1", "a2"]


# ------------------------------------------------------------ delta logging

async def test_unchanged_within_24h_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_extract(monkeypatch, [ex(29800)])
    clock = Clock()
    w = make_worker(FakeFetcher(ok()), clock=clock)
    src = make_source()
    assert await w.process_source(src) == "ok"
    clock.t = T0 + timedelta(hours=6)
    assert await w.process_source(src) == "ok"
    assert [p.observed_at for p in w.db.state.points["src-1:"]] == [T0]
    assert w.db.state.outcomes["src-1"]["kind"] == "success"


async def test_change_writes_a_point(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_extract(monkeypatch, [ex(29800)], [ex(24800)], [ex(24800, in_stock=False)])
    clock = Clock()
    w = make_worker(FakeFetcher(ok()), clock=clock)
    for h in (0, 1, 2):
        clock.t = T0 + timedelta(hours=h)
        await w.process_source(make_source())
    assert [(p.price_cents, p.in_stock) for p in w.db.state.points["src-1:"]] == [
        (29800, True), (24800, True), (24800, False)]


async def test_unchanged_after_24h_writes_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_extract(monkeypatch, [ex(29800)])
    clock = Clock()
    w = make_worker(FakeFetcher(ok()), clock=clock)
    await w.process_source(make_source())
    clock.t = T0 + timedelta(hours=25)
    await w.process_source(make_source())
    assert len(w.db.state.points["src-1:"]) == 2


async def test_variants_are_tracked_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_extract(monkeypatch, [ex(5000, key="M|black"), ex(5000, False, "XL|black"), ex(1, key="M|black")])
    w = make_worker(FakeFetcher(ok()))
    await w.process_source(make_source())
    assert set(w.db.state.variants["src-1"]) == {"M|black", "XL|black"}
    # duplicate key: first wins, the later one is ignored
    assert [p.price_cents for p in w.db.state.points["src-1:M|black"]] == [5000]


async def test_next_check_uses_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_extract(monkeypatch, [ex(29800)])
    w = make_worker(FakeFetcher(ok()))
    await w.process_source(make_source(check_interval_mins=60))
    gap = w.db.state.outcomes["src-1"]["next_check_at"] - T0
    assert timedelta(minutes=54) <= gap <= timedelta(minutes=66)


# --------------------------------------------------------- failure counting

async def test_failing_at_exactly_three_then_reset_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_extract(monkeypatch, [], [], [], [ex(29800)])
    w = make_worker(FakeFetcher(ok()))
    statuses = []
    for _ in range(3):
        assert await w.process_source(make_source()) == "failed"
        statuses.append((w.db.state.failures["src-1"], w.db.state.status["src-1"]))
    assert statuses == [(1, "active"), (2, "active"), (3, "failing")]
    assert w.db.state.outcomes["src-1"]["last_error"] == NO_PRICE

    assert await w.process_source(make_source(status="failing")) == "ok"
    assert w.db.state.failures["src-1"] == 0
    assert w.db.state.status["src-1"] == "active"
    assert w.db.state.outcomes["src-1"]["last_error"] is None
    assert len(calls) == 4


async def test_403_is_a_blocked_failure() -> None:
    w = make_worker(FakeFetcher(FetchResult("blocked", "https://x", 403, error="HTTP 403")))
    assert await w.process_source(make_source()) == "failed"
    assert w.db.state.outcomes["src-1"]["last_error"] == BLOCKED


async def test_network_error_is_a_failure() -> None:
    w = make_worker(FakeFetcher(FetchResult("network_error", "https://x", error="timed out")))
    await w.process_source(make_source())
    assert "couldn't be reached (timed out)" in w.db.state.outcomes["src-1"]["last_error"]


async def test_invalid_extraction_is_never_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = [Extracted(298.0, "USD", True, None, "x"), Extracted(-1, "USD", True, "M", "x"),  # type: ignore[arg-type]
           Extracted(True, "USD", True, "S", "x")]  # type: ignore[arg-type]
    patch_extract(monkeypatch, bad)
    w = make_worker(FakeFetcher(ok()))
    assert await w.process_source(make_source()) == "failed"
    assert w.db.state.points == {}


async def test_extractor_crash_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(html: str, url: str) -> list[Extracted]:
        raise KeyError("offers")

    monkeypatch.setattr(extract_base, "extract", boom)
    w = make_worker(FakeFetcher(ok()))
    assert await w.process_source(make_source()) == "failed"
    assert w.db.state.failures["src-1"] == 1


# ------------------------------------------------------- not implemented

async def test_not_implemented_extract_is_not_a_failure(caplog: pytest.LogCaptureFixture) -> None:
    # The real stub raises NotImplementedError.
    w = make_worker(FakeFetcher(ok()))
    with caplog.at_level(logging.WARNING, logger="scheduler"):
        for _ in range(4):
            assert await w.process_source(make_source(id="src-1")) == "not_implemented"
        assert await w.process_source(make_source(id="src-2")) == "not_implemented"
    assert w.db.state.failures == {}
    assert w.db.state.outcomes["src-1"]["kind"] == "skipped"
    assert w.db.state.outcomes["src-1"]["last_error"] == NOT_BUILT
    assert w.db.state.outcomes["src-1"]["next_check_at"] > T0 + timedelta(hours=5)
    assert sum("not implemented" in r.message for r in caplog.records) == 1


async def test_learned_path_bypasses_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_extract(monkeypatch, [])
    w = make_worker(FakeFetcher(ok(FARMRIO_HTML)))
    assert await w.process_source(make_source(extractor_config=LEARNED_FARMRIO, title=None)) == "ok"
    assert calls == []
    [p] = w.db.state.points["src-1:"]
    assert (p.price_cents, p.in_stock) == (29800, True)
    assert w.db.state.outcomes["src-1"]["title"] == "Multicolor Rustic Flowers Sleeveless Ruched Maxi Dress"


async def test_broken_learned_path_is_no_price_failure() -> None:
    cfg = {**LEARNED_FARMRIO, "path": ["offers", 0, "gone"]}
    w = make_worker(FakeFetcher(ok(FARMRIO_HTML)))
    assert await w.process_source(make_source(extractor_config=cfg)) == "failed"
    assert w.db.state.outcomes["src-1"]["last_error"] == NO_PRICE


@pytest.mark.parametrize("status", ["paused", "unsupported"])
async def test_paused_and_unsupported_are_skipped(status: str) -> None:
    f = FakeFetcher(ok())
    w = make_worker(f)
    assert await w.process_source(make_source(status=status)) == "skipped"
    assert f.urls == []


# ------------------------------------------------------------- alerts hook

async def test_alerts_dispatched_only_for_written_points(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_extract(monkeypatch, [ex(24800)])
    evaluated: list[PricePoint] = []
    monkeypatch.setattr(alerts, "evaluate", lambda w, latest, h: evaluated.append(latest) or ["new_low"])
    db = FakeDB()
    db.state.watches["src-1"] = [make_watch()]
    db.state.emails["u-1"] = "a@test.dev"
    clock = Clock()
    w = make_worker(FakeFetcher(ok()), db=db, clock=clock)
    await w.process_source(make_source())
    clock.t = T0 + timedelta(hours=1)
    await w.process_source(make_source())   # unchanged: no point, no alert
    assert len(evaluated) == 1
    assert len(w.sender.sent) == 1


async def test_alert_crash_does_not_fail_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_extract(monkeypatch, [ex(24800)])

    async def boom(*a: object, **k: object) -> int:
        raise RuntimeError("db hiccup")

    monkeypatch.setattr("scheduler.dispatch_alerts", boom)
    w = make_worker(FakeFetcher(ok()))
    assert await w.process_source(make_source()) == "ok"


# ------------------------------------------------------------------ loop

async def test_run_once_processes_the_claimed_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_extract(monkeypatch, [ex(1000)])
    db = FakeDB()
    db.state.claim_queue = [[make_source(id="a"), make_source(id="b")]]
    w = make_worker(FakeFetcher(ok()), db=db)
    assert await w.run_once() == 2
    assert set(db.state.outcomes) == {"a", "b"}
    assert await w.run_once() == 0


async def test_run_forever_stops_on_event() -> None:
    w = make_worker(FakeFetcher(ok()))
    w.settings = Settings(idle_sleep_s=10)
    stop = asyncio.Event()
    task = asyncio.create_task(w.run_forever(stop))
    await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=1)


# --------------------------------------------------------------- with DB

@requires_db
async def test_end_to_end_against_postgres(db_url: str, database: Database) -> None:
    sid = seed_source(db_url, extractor_config=json.dumps(LEARNED_FARMRIO), failures=2)
    other = seed_source(db_url)   # registry extract: still a stub
    clock = Clock(datetime.now(UTC))
    w = Worker(database, FakeFetcher(ok(FARMRIO_HTML)), FakeSender(),
               Settings(app_url="https://app.test"), clock=clock)

    assert await w.run_once() == 2
    assert sql(db_url, "select price_cents, in_stock from price_points") == [(29800, True)]
    assert sql(db_url, "select status::text, consecutive_failures, last_error, title is not null "
                       "from product_sources where id = %s", (sid,)) == [("active", 0, None, True)]
    assert sql(db_url, "select consecutive_failures, last_error from product_sources where id = %s",
               (other,)) == [(0, NOT_BUILT)]
    # Both rescheduled hours out, so the next poll finds nothing.
    assert await w.run_once() == 0
