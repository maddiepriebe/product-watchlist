from models import AlertReason, PricePoint, Watch


def evaluate(watch: Watch, latest: PricePoint, history: list[PricePoint]) -> list[AlertReason]:
    """Which alerts should fire for this watch, given a new price point.

    Rules: below_threshold, pct_drop vs 30-day median, new_low vs 90-day
    minimum, back_in_stock. Respects muted_until and min_alert_gap_hrs.
    Suppresses re-alerts until the price recovers at least 5% from the
    price that last triggered.

    Call conventions (set by the scheduler):
      - `history` is the same variant's earlier points, oldest first,
        covering at least the 90 days before `latest`; it excludes `latest`.
      - "now" is `latest.observed_at`.
      - `watch.recent_alerts` is newest first and includes every alert
        this function caused that was then sent.
    """
    raise NotImplementedError
