import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import alerts
import notify
from db import Database
from logs import reset_warn_once
from models import PricePoint, Watch
from notify import compose, dispatch_alerts, money, reason_line
from tests.fakes import FakeDB, FakeSender, Notification, make_source, make_watch
from tests.pgtest import USER_ID, database, db_url, requires_db, seed_source, sql  # noqa: F401

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_warn_once()


def setup_db(watches: list) -> tuple[FakeDB, str]:
    db = FakeDB()
    src = make_source()
    db.state.watches[src.id] = watches
    db.state.emails["u-1"] = "maddie@test.dev"
    vid = "src-1:M|black"
    db.state.points[vid] = [
        PricePoint(NOW - timedelta(days=20), 30000, True),
        PricePoint(NOW - timedelta(days=10), 29000, True),
        PricePoint(NOW, 24800, True),
    ]
    return db, vid


@pytest.mark.parametrize(
    "cents, currency, expected",
    [(29800, "USD", "$298.00"), (129850, "USD", "$1,298.50"), (5, "USD", "$0.05"),
     (0, "USD", "$0.00"), (4000, "GBP", "£40.00"), (4000, "SEK", "40.00 SEK")],
)
def test_money(cents: int, currency: str, expected: str) -> None:
    assert money(cents, currency) == expected


async def test_dispatch_writes_notification_and_sends_email(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_evaluate(watch: Watch, latest: PricePoint, history: list[PricePoint]) -> list:
        seen.update(watch=watch, latest=latest, history=history)
        return ["below_threshold", "new_low"]

    monkeypatch.setattr(alerts, "evaluate", fake_evaluate)
    db, vid = setup_db([make_watch()])
    sender = FakeSender()
    latest = db.state.points[vid][-1]

    n = await dispatch_alerts(db, sender, app_url="https://app.test", source=make_source(),
                              variant_id=vid, variant_key="M|black", latest=latest)

    assert n == 2
    # evaluate got the call conventions in alerts.py
    assert seen["latest"] == latest
    assert [p.price_cents for p in seen["history"]] == [30000, 29000]   # oldest first, excludes latest
    assert seen["watch"].alert_pct_drop == Decimal("15.00")
    notes = db.state.notifications
    assert [(x.reason, x.price_cents, x.delivered, x.error) for x in notes] == [
        ("below_threshold", 24800, True, None), ("new_low", 24800, True, None)]
    assert notes[0].variant_id == vid and notes[0].source_id == "src-1"
    to, email, key = sender.sent[0]
    assert to == "maddie@test.dev"
    assert key == f"notification-{notes[0].id}"
    assert email.subject == "Rustic Flowers Maxi Dress dropped to $248.00"
    assert "Below your $250.00 alert." in email.text
    assert "https://farmrio.com/products/rustic" in email.text
    assert "https://app.test/watchlist" in email.text
    assert 'href="https://app.test/watchlist"' in email.html


async def test_recent_alerts_passed_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Watch] = []
    monkeypatch.setattr(alerts, "evaluate", lambda w, l, h: calls.append(w) or [])
    db, vid = setup_db([make_watch()])
    db.state.notifications += [
        Notification(1, "w-1", "src-1", vid, "new_low", 29000, NOW - timedelta(days=5), delivered=True),
        Notification(2, "w-1", "src-1", vid, "pct_drop", 28000, NOW - timedelta(days=2), delivered=True),
        Notification(3, "w-1", "src-1", vid, "below_threshold", 27000, NOW - timedelta(days=1), delivered=False),
    ]
    await dispatch_alerts(db, FakeSender(), app_url="https://app.test", source=make_source(),
                          variant_id=vid, variant_key="M|black", latest=db.state.points[vid][-1])
    assert [a.reason for a in calls[0].recent_alerts] == ["pct_drop", "new_low"]


async def test_email_failure_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts, "evaluate", lambda w, l, h: ["new_low"])
    db, vid = setup_db([make_watch()])
    n = await dispatch_alerts(db, FakeSender(fail=True), app_url="https://app.test", source=make_source(),
                              variant_id=vid, variant_key="M|black", latest=db.state.points[vid][-1])
    assert n == 0
    [note] = db.state.notifications
    assert note.delivered is False
    assert "resend is down" in (note.error or "")


async def test_not_implemented_is_skipped_and_logged_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The real stub raises NotImplementedError; don't patch it.
    db, vid = setup_db([make_watch(id="w-1"), make_watch(id="w-2")])
    sender = FakeSender()
    with caplog.at_level(logging.WARNING, logger="notify"):
        for _ in range(3):
            n = await dispatch_alerts(db, sender, app_url="https://app.test", source=make_source(),
                                      variant_id=vid, variant_key="M|black", latest=db.state.points[vid][-1])
            assert n == 0
    assert sender.sent == [] and db.state.notifications == []
    assert sum("not implemented" in r.message for r in caplog.records) == 1


async def test_evaluate_crash_skips_only_that_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    def flaky(w: Watch, l: PricePoint, h: list) -> list:
        if w.id == "w-1":
            raise ValueError("bug")
        return ["new_low"]

    monkeypatch.setattr(alerts, "evaluate", flaky)
    db, vid = setup_db([make_watch(id="w-1"), make_watch(id="w-2")])
    n = await dispatch_alerts(db, FakeSender(), app_url="https://app.test", source=make_source(),
                              variant_id=vid, variant_key="M|black", latest=db.state.points[vid][-1])
    assert n == 1
    assert [x.watch_id for x in db.state.notifications] == ["w-2"]


async def test_non_email_and_unmatched_watches_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(alerts, "evaluate", lambda w, l, h: called.append(w.id) or ["new_low"])
    db, vid = setup_db([
        make_watch(id="w-ntfy", channel="ntfy"),
        make_watch(id="w-xl", watched_variant_keys=["XL|black"]),
        make_watch(id="w-m", watched_variant_keys=["M|black"]),
    ])
    await dispatch_alerts(db, FakeSender(), app_url="https://app.test", source=make_source(),
                          variant_id=vid, variant_key="M|black", latest=db.state.points[vid][-1])
    assert called == ["w-m"]


async def test_owner_without_email_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts, "evaluate", lambda w, l, h: ["new_low"])
    db, vid = setup_db([make_watch(user_id="u-nobody")])
    n = await dispatch_alerts(db, FakeSender(), app_url="https://app.test", source=make_source(),
                              variant_id=vid, variant_key="M|black", latest=db.state.points[vid][-1])
    assert n == 0 and db.state.notifications == []


def test_reason_lines() -> None:
    latest = PricePoint(NOW, 25500, True)
    history = [PricePoint(NOW - timedelta(days=d), 30000, True) for d in (40, 20, 10)]
    w = make_watch()
    assert reason_line("below_threshold", w, latest, history, "") == "Below your $250.00 alert."
    assert reason_line("pct_drop", w, latest, history, "") == "15% under its 30-day typical price."
    assert reason_line("pct_drop", w, latest, [], "") == "At least 15% under its 30-day typical price."
    assert reason_line("new_low", w, latest, history, "") == "Lowest price in 90 days."
    assert reason_line("back_in_stock", w, latest, history, "M") == "Back in stock in M."
    assert reason_line("back_in_stock", w, latest, history, "M|black") == "Back in stock in M, black."
    assert reason_line("back_in_stock", w, latest, history, "") == "Back in stock."


def test_back_in_stock_copy_and_nickname() -> None:
    e = compose("back_in_stock", watch=make_watch(nickname="Green dress"), source=make_source(),
                variant_key="M", latest=PricePoint(NOW, 29800, True), history=[], app_url="https://app.test")
    assert e.subject == "Green dress is back in stock in M"
    assert e.text.startswith("Green dress is back in stock at farmrio.com for $298.00.\nBack in stock in M.")


def test_html_is_escaped() -> None:
    e = compose("new_low", watch=make_watch(nickname="<b>Dress</b>"), source=make_source(),
                variant_key="", latest=PricePoint(NOW, 100, True), history=[], app_url="https://app.test")
    assert "<b>Dress</b>" not in e.html and "&lt;b&gt;" in e.html


def test_resend_sender_is_an_email_sender() -> None:
    assert hasattr(notify.ResendSender("re_test", "alerts@test.dev"), "send")


@requires_db
async def test_dispatch_against_postgres(
    db_url: str, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alerts, "evaluate", lambda w, l, h: ["below_threshold"])
    sid = seed_source(db_url)
    [(wid,)] = sql(db_url, "insert into watches (user_id, alert_below_cents) values (%s, 25000) returning id::text", (USER_ID,))
    sql(db_url, "insert into watch_sources (watch_id, source_id) values (%s, %s)", (wid, sid))
    async with database.transaction() as q:
        [src] = await q.claim_due_sources(1, 15)
        vid = await q.upsert_variant(sid, "M|black")
        latest = PricePoint(datetime.now(UTC), 24800, True)
        await q.insert_price_point(vid, latest)
    sender = FakeSender()
    assert await dispatch_alerts(database, sender, app_url="https://app.test", source=src,
                                 variant_id=vid, variant_key="M|black", latest=latest) == 1
    assert sql(db_url, "select reason::text, price_cents, delivered, error from notifications") == [
        ("below_threshold", 24800, True, None)]
    assert sender.sent[0][0] == "a@test.dev"


def test_subject_says_dropped_only_after_a_drop() -> None:
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    latest = PricePoint(t0 + timedelta(hours=6), 24800, True)
    kw = dict(watch=make_watch(), source=make_source(), variant_key="", app_url="https://app.test")

    first = compose("below_threshold", latest=latest, history=[], **kw)
    assert first.subject == "Rustic Flowers Maxi Dress is $248.00"

    after_drop = compose("below_threshold", latest=latest,
                         history=[PricePoint(t0, 30000, True)], **kw)
    assert after_drop.subject == "Rustic Flowers Maxi Dress dropped to $248.00"
