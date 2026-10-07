"""Integration tests for db.py against a real Postgres. Skipped without TEST_DATABASE_URL."""

import asyncio
from datetime import UTC, datetime, timedelta

from db import Database, split_variant_key
from models import PricePoint
from tests.pgtest import USER_ID, database, db_url, requires_db, seed_source, sql  # noqa: F401

def test_split_variant_key() -> None:
    assert split_variant_key(None) == ("", None, None)
    assert split_variant_key("") == ("", None, None)
    assert split_variant_key("M") == ("M", "M", None)
    assert split_variant_key("M|black") == ("M|black", "M", "black")
    assert split_variant_key("|black") == ("|black", None, "black")


@requires_db
async def test_claim_takes_only_due_checkable_sources_and_leases_them(db_url: str, database: Database) -> None:
    due = seed_source(db_url)
    failing = seed_source(db_url, status="failing")
    seed_source(db_url, due=False)
    seed_source(db_url, status="paused")
    seed_source(db_url, status="unsupported")

    async with database.transaction() as q:
        claimed = await q.claim_due_sources(limit=10, lease_mins=15)
    assert {s.id for s in claimed} == {due, failing}
    assert claimed[0].extractor_config == {}

    # Leased: a second claim finds nothing.
    async with database.transaction() as q:
        assert await q.claim_due_sources(limit=10, lease_mins=15) == []
    [(mins,)] = sql(db_url, "select extract(epoch from next_check_at - now()) / 60 from product_sources where id = %s", (due,))
    assert 14 < float(mins) <= 15


@requires_db
async def test_parallel_claims_are_disjoint(db_url: str) -> None:
    for _ in range(10):
        seed_source(db_url)
    a, b = Database(db_url, size=1), Database(db_url, size=1)
    try:
        async def claim(d: Database) -> list[str]:
            async with d.transaction() as q:
                rows = await q.claim_due_sources(limit=6, lease_mins=15)
                await asyncio.sleep(0.05)   # hold the row locks while the other claims
                return [r.id for r in rows]

        ra, rb = await asyncio.gather(claim(a), claim(b))
    finally:
        await a.close()
        await b.close()
    assert not set(ra) & set(rb)
    assert len(ra) + len(rb) == 10


@requires_db
async def test_failure_counting_flips_to_failing_at_three(db_url: str, database: Database) -> None:
    sid = seed_source(db_url)
    later = datetime.now(UTC) + timedelta(hours=6)
    results = []
    for _ in range(4):
        async with database.transaction() as q:
            results.append(await q.record_failure(sid, "boom", later))
    assert results == [(1, "active"), (2, "active"), (3, "failing"), (4, "failing")]

    async with database.transaction() as q:
        await q.record_success(sid, later, title="Dress", image_url="https://img.test/a.jpg")
    [(status, failures, err, title)] = sql(
        db_url, "select status::text, consecutive_failures, last_error, title from product_sources where id = %s", (sid,))
    assert (status, failures, err, title) == ("active", 0, None, "Dress")


@requires_db
async def test_failure_never_overrides_paused(db_url: str, database: Database) -> None:
    sid = seed_source(db_url, status="paused", failures=5)
    async with database.transaction() as q:
        assert await q.record_failure(sid, "boom", datetime.now(UTC)) == (6, "paused")
        await q.record_success(sid, datetime.now(UTC))
    assert sql(db_url, "select status::text from product_sources where id = %s", (sid,)) == [("paused",)]


@requires_db
async def test_success_keeps_existing_title(db_url: str, database: Database) -> None:
    sid = seed_source(db_url)
    sql(db_url, "update product_sources set title = 'Mine' where id = %s", (sid,))
    async with database.transaction() as q:
        await q.record_success(sid, datetime.now(UTC), title="Theirs")
    assert sql(db_url, "select title from product_sources where id = %s", (sid,)) == [("Mine",)]


@requires_db
async def test_record_skipped_does_not_count(db_url: str, database: Database) -> None:
    sid = seed_source(db_url, failures=2)
    async with database.transaction() as q:
        await q.record_skipped(sid, "not built yet", datetime.now(UTC))
    assert sql(db_url, "select consecutive_failures, last_error from product_sources where id = %s", (sid,)) == [
        (2, "not built yet")]


@requires_db
async def test_variants_points_and_history(db_url: str, database: Database) -> None:
    sid = seed_source(db_url)
    now = datetime.now(UTC).replace(microsecond=0)
    async with database.transaction() as q:
        v1 = await q.upsert_variant(sid, "M|black")
        assert await q.upsert_variant(sid, "M|black") == v1
        v0 = await q.upsert_variant(sid, None)
        assert v0 != v1
        assert await q.latest_point(v1) is None
        for days, cents in [(100, 9000), (60, 10000), (10, 8000), (0, 7000)]:
            await q.insert_price_point(v1, PricePoint(now - timedelta(days=days), cents, True))
        latest = await q.latest_point(v1)
        hist = await q.history(v1, before=now)
    assert sql(db_url, "select variant_key, size, color from variants where id = %s", (v1,)) == [("M|black", "M", "black")]
    assert sql(db_url, "select variant_key, size, color from variants where id = %s", (v0,)) == [("", None, None)]
    assert latest == PricePoint(now, 7000, True, "USD")
    assert [p.price_cents for p in hist] == [10000, 8000]   # oldest first, excludes latest and >91d


@requires_db
async def test_watches_alerts_notifications_and_email(db_url: str, database: Database) -> None:
    sid = seed_source(db_url)
    w_any, w_m, w_xl, w_archived = (sql(db_url, "select gen_random_uuid()::text")[0][0] for _ in range(4))
    sql(db_url, "insert into watches (id, user_id) values (%s, %s)", (w_any, USER_ID))
    sql(db_url, "insert into watches (id, user_id, watched_variant_keys, alert_pct_drop) values (%s, %s, '{M|black}', 15)", (w_m, USER_ID))
    sql(db_url, "insert into watches (id, user_id, watched_variant_keys) values (%s, %s, '{XL|black}')", (w_xl, USER_ID))
    sql(db_url, "insert into watches (id, user_id, archived_at) values (%s, %s, now())", (w_archived, USER_ID))
    for w in (w_any, w_m, w_xl, w_archived):
        sql(db_url, "insert into watch_sources (watch_id, source_id) values (%s, %s)", (w, sid))

    now = datetime.now(UTC)
    async with database.transaction() as q:
        vid = await q.upsert_variant(sid, "M|black")
        watches = await q.watches_for_variant(sid, "M|black")
        assert {w.id for w in watches} == {w_any, w_m}
        n1 = await q.insert_notification(watch_id=w_m, source_id=sid, variant_id=vid,
                                         reason="new_low", price_cents=5000, sent_at=now - timedelta(days=2))
        n2 = await q.insert_notification(watch_id=w_m, source_id=sid, variant_id=vid,
                                         reason="pct_drop", price_cents=4000, sent_at=now - timedelta(days=1))
        n3 = await q.insert_notification(watch_id=w_m, source_id=sid, variant_id=vid,
                                         reason="below_threshold", price_cents=3000, sent_at=now)
        await q.mark_notification(n1, delivered=True, error=None)
        await q.mark_notification(n2, delivered=True, error=None)
        await q.mark_notification(n3, delivered=False, error="resend down")
        recent = await q.recent_alerts(w_m, since=now - timedelta(days=90))
        email = await q.user_email(USER_ID)

    assert [a.reason for a in recent] == ["below_threshold", "pct_drop", "new_low"]   # newest first; the undelivered row counts too
    model = next(w for w in watches if w.id == w_m).to_model(recent)
    assert str(model.alert_pct_drop) == "15.00"
    assert model.recent_alerts == recent
    assert email == "a@test.dev"
