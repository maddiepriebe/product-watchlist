"""Plain data shared across the worker. No I/O here.

Prices are integer cents everywhere. Timestamps are timezone-aware UTC.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

# Mirrors the `alert_reason` enum in supabase/migrations.
AlertReason = Literal["below_threshold", "pct_drop", "new_low", "back_in_stock"]


@dataclass(frozen=True)
class PricePoint:
    """One observation of one variant (a `price_points` row)."""

    observed_at: datetime
    price_cents: int
    in_stock: bool
    currency: str = "USD"


@dataclass(frozen=True)
class SentAlert:
    """A previously sent alert for a watch (a `notifications` row)."""

    sent_at: datetime
    reason: AlertReason
    price_cents: int


@dataclass(frozen=True)
class Watch:
    """The alert-relevant slice of a `watches` row.

    `recent_alerts` holds this watch's past notifications, newest first —
    the state evaluate() needs for gap and recovery debouncing.
    """

    id: str
    alert_below_cents: int | None = None
    alert_pct_drop: Decimal | None = None  # percent, e.g. Decimal("15.00")
    alert_on_new_low: bool = True
    alert_on_restock: bool = True
    muted_until: datetime | None = None
    min_alert_gap_hrs: int = 24
    recent_alerts: tuple[SentAlert, ...] = field(default_factory=tuple)
