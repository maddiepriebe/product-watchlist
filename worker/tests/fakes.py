"""In-memory stand-ins for Database/Queries and the email sender.

Only what notify.py and scheduler.py call. Not conftest.py on purpose (that
name belongs to the stub tests).
"""

import itertools
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator

from db import SourceRow, WatchRow, split_variant_key
from models import PricePoint, SentAlert
from notify import Email


def make_source(**kw: Any) -> SourceRow:
    base = dict(
        id="src-1", canonical_url="https://farmrio.com/products/rustic", retailer="farmrio.com",
        title="Rustic Flowers Maxi Dress", image_url=None, extractor="jsonld",
        extractor_config={}, status="active", check_interval_mins=360, consecutive_failures=0,
    )
    base.update(kw)
    return SourceRow(**base)


def make_watch(**kw: Any) -> WatchRow:
    base = dict(
        id="w-1", user_id="u-1", nickname=None, channel="email", watched_variant_keys=None,
        alert_below_cents=25000, alert_pct_drop=Decimal("15.00"), alert_on_new_low=True,
        alert_on_restock=True, muted_until=None, min_alert_gap_hrs=24,
    )
    base.update(kw)
    return WatchRow(**base)


@dataclass
class Notification:
    id: int
    watch_id: str
    source_id: str
    variant_id: str
    reason: str
    price_cents: int
    sent_at: datetime
    delivered: bool = False
    error: str | None = None


@dataclass
class FakeState:
    sources: dict[str, SourceRow] = field(default_factory=dict)
    # source_id -> {variant_key: variant_id}
    variants: dict[str, dict[str, str]] = field(default_factory=dict)
    points: dict[str, list[PricePoint]] = field(default_factory=dict)
    watches: dict[str, list[WatchRow]] = field(default_factory=dict)   # by source_id
    emails: dict[str, str] = field(default_factory=dict)
    notifications: list[Notification] = field(default_factory=list)
    # source_id -> the latest record_* call
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    claim_queue: list[list[SourceRow]] = field(default_factory=list)
    _ids: Any = field(default_factory=lambda: itertools.count(1))


class FakeQueries:
    def __init__(self, s: FakeState) -> None:
        self.s = s

    async def claim_due_sources(self, limit: int, lease_mins: int) -> list[SourceRow]:
        return self.s.claim_queue.pop(0) if self.s.claim_queue else []

    async def record_success(self, source_id: str, next_check_at: datetime,
                             title: str | None = None, image_url: str | None = None) -> None:
        self.s.failures[source_id] = 0
        if self.s.status.get(source_id, "active") == "failing":
            self.s.status[source_id] = "active"
        self.s.outcomes[source_id] = {"kind": "success", "next_check_at": next_check_at,
                                      "title": title, "image_url": image_url, "last_error": None}

    async def record_failure(self, source_id: str, error: str, next_check_at: datetime) -> tuple[int, str]:
        n = self.s.failures.get(source_id, 0) + 1
        self.s.failures[source_id] = n
        status = self.s.status.get(source_id, "active")
        if status == "active" and n >= 3:
            status = "failing"
        self.s.status[source_id] = status
        self.s.outcomes[source_id] = {"kind": "failure", "last_error": error, "next_check_at": next_check_at}
        return n, status

    async def record_skipped(self, source_id: str, note: str, next_check_at: datetime) -> None:
        self.s.outcomes[source_id] = {"kind": "skipped", "last_error": note, "next_check_at": next_check_at}

    async def upsert_variant(self, source_id: str, variant_key: str | None) -> str:
        key, _, _ = split_variant_key(variant_key)
        by_key = self.s.variants.setdefault(source_id, {})
        return by_key.setdefault(key, f"{source_id}:{key}")

    async def latest_point(self, variant_id: str) -> PricePoint | None:
        pts = self.s.points.get(variant_id, [])
        return max(pts, key=lambda p: p.observed_at) if pts else None

    async def insert_price_point(self, variant_id: str, point: PricePoint) -> None:
        self.s.points.setdefault(variant_id, []).append(point)

    async def history(self, variant_id: str, before: datetime, days: int = 91) -> list[PricePoint]:
        pts = [p for p in self.s.points.get(variant_id, []) if p.observed_at < before]
        return sorted(pts, key=lambda p: p.observed_at)

    async def watches_for_variant(self, source_id: str, variant_key: str) -> list[WatchRow]:
        return [w for w in self.s.watches.get(source_id, [])
                if w.watched_variant_keys is None or variant_key in w.watched_variant_keys]

    async def recent_alerts(self, watch_id: str, since: datetime) -> tuple[SentAlert, ...]:
        rows = [n for n in self.s.notifications if n.watch_id == watch_id and n.sent_at >= since]
        rows.sort(key=lambda n: n.sent_at, reverse=True)
        return tuple(SentAlert(n.sent_at, n.reason, n.price_cents) for n in rows)  # type: ignore[arg-type]

    async def insert_notification(self, **kw: Any) -> int:
        n = Notification(id=next(self.s._ids), **kw)
        self.s.notifications.append(n)
        return n.id

    async def mark_notification(self, notification_id: int, *, delivered: bool, error: str | None) -> None:
        for i, n in enumerate(self.s.notifications):
            if n.id == notification_id:
                self.s.notifications[i] = replace(n, delivered=delivered, error=error)

    async def user_email(self, user_id: str) -> str | None:
        return self.s.emails.get(user_id)


class FakeDB:
    def __init__(self, state: FakeState | None = None) -> None:
        self.state = state or FakeState()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[FakeQueries]:
        yield FakeQueries(self.state)

    async def close(self) -> None:
        pass


class FakeSender:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, Email, str]] = []

    async def send(self, *, to: str, email: Email, idempotency_key: str) -> None:
        if self.fail:
            raise RuntimeError("resend is down")
        self.sent.append((to, email, idempotency_key))
