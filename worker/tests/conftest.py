"""Shared helpers for the worker test suites.

Real fixtures are saved pages (see scripts/spike.py); synthetic ones live in
fixtures/synthetic/ and are hand-written, obviously fake HTML.

Import helpers with `from tests.conftest import ...` (tests/ is a package and
pytest's pythonpath is the worker root).
"""

from __future__ import annotations

import dataclasses
import functools
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from alerts import evaluate
from models import AlertReason, PricePoint, SentAlert, Watch

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def fixture_path(prefix: str) -> Path:
    """Find the single real fixture whose filename contains `prefix`."""
    matches = sorted(FIXTURES.glob(f"fixture-*{prefix}*.html"))
    assert len(matches) == 1, f"expected exactly one fixture for {prefix!r}, got {matches}"
    return matches[0]


@functools.cache
def read_fixture(prefix: str) -> str:
    return fixture_path(prefix).read_text(encoding="utf-8", errors="replace")


def read_synthetic(name: str) -> str:
    return (SYNTHETIC / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- alerts ----

def hours(n: float) -> timedelta:
    return timedelta(hours=n)


def days(n: float) -> timedelta:
    return timedelta(days=n)


def pt(at: datetime, cents: int, in_stock: bool = True) -> PricePoint:
    return PricePoint(observed_at=at, price_cents=cents, in_stock=in_stock)


def daily_history(
    prices: list[int], end: datetime = T0, step: timedelta = timedelta(days=1)
) -> list[PricePoint]:
    """Points oldest-first, the last one `step` before `end`."""
    n = len(prices)
    return [pt(end - step * (n - i), c) for i, c in enumerate(prices)]


def flat_history(cents: int, n_days: int = 100, end: datetime = T0) -> list[PricePoint]:
    """One point per day for n_days, ending 1 day before `end`."""
    return daily_history([cents] * n_days, end=end)


def make_watch(**kw) -> Watch:
    """Watch with every rule OFF unless asked for. The gap defaults to 0 so
    tests only see the gap when they set it."""
    base = dict(
        id="w1",
        alert_below_cents=None,
        alert_pct_drop=None,
        alert_on_new_low=False,
        alert_on_restock=False,
        muted_until=None,
        min_alert_gap_hrs=0,
        recent_alerts=(),
    )
    base.update(kw)
    if isinstance(base["alert_pct_drop"], (int, float, str)):
        base["alert_pct_drop"] = Decimal(str(base["alert_pct_drop"]))
    return Watch(**base)


def sent(at: datetime, reason: AlertReason, cents: int) -> SentAlert:
    return SentAlert(sent_at=at, reason=reason, price_cents=cents)


class Scheduler:
    """Simulates the scheduler: one evaluate() per new point, recording sends.

    Sent alerts are prepended (newest first) to the watch via
    dataclasses.replace before the next call, as the evaluate docstring says.
    """

    def __init__(self, watch: Watch, history: list[PricePoint] | None = None):
        self.watch = watch
        self.history: list[PricePoint] = list(history or [])
        self.fired: list[tuple[datetime, list[AlertReason]]] = []

    def observe(self, at: datetime, cents: int, in_stock: bool = True) -> list[AlertReason]:
        latest = pt(at, cents, in_stock)
        reasons = evaluate(self.watch, latest, list(self.history))
        assert isinstance(reasons, list)
        if reasons:
            new = tuple(sent(at, r, cents) for r in reasons)
            self.watch = dataclasses.replace(
                self.watch, recent_alerts=new + self.watch.recent_alerts
            )
            self.fired.append((at, reasons))
        self.history.append(latest)
        return reasons

    def count(self, reason: AlertReason) -> int:
        return sum(r.count(reason) for _, r in self.fired)
