"""Tests for alerts.evaluate(watch, latest, history) -> list[AlertReason].

Conventions (from the evaluate docstring): history is oldest-first, excludes
`latest`, and covers >= 90 days; "now" is latest.observed_at; recent_alerts is
newest first. Series tests simulate the scheduler with tests.conftest.Scheduler,
which prepends every sent alert to the watch via dataclasses.replace.

Where the docstring is silent, the choice made is marked `# CONTRACT CHOICE:`
directly above the test.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from alerts import evaluate
from tests.conftest import (
    T0,
    Scheduler,
    daily_history,
    days,
    flat_history,
    hours,
    make_watch,
    pt,
    sent,
)

VALID_REASONS = {"below_threshold", "pct_drop", "new_low", "back_in_stock"}
ALL_ON = dict(alert_below_cents=6000, alert_pct_drop=Decimal("20.00"),
              alert_on_new_low=True, alert_on_restock=True)


def step(i: int, spacing_hrs: float = 30):
    """Time of the i-th scheduler check after T0 (default spacing > 24h gap)."""
    return T0 + hours(spacing_hrs * i)


def ev(watch, cents, history, at=T0, in_stock=True):
    return evaluate(watch, pt(at, cents, in_stock), history)


# --------------------------------------------------------------- flat / base --

def test_flat_series_fires_nothing_with_all_rules_on():
    # Equal to the 90-day minimum is not a new low; median == price so no pct drop.
    watch = make_watch(alert_below_cents=3000, alert_pct_drop=Decimal("10"),
                       alert_on_new_low=True, alert_on_restock=True, min_alert_gap_hrs=24)
    s = Scheduler(watch, flat_history(5000, 100))
    for i in range(12):
        assert s.observe(step(i), 5000) == []
    assert s.fired == []


def test_single_flat_check_returns_empty_list_type():
    result = ev(make_watch(**ALL_ON), 9000, flat_history(9000))
    assert result == []
    assert isinstance(result, list)


def test_no_rules_configured_never_fires():
    # Everything that could trigger is true, but every rule is off.
    history = flat_history(10000, 100)
    history[-1] = pt(history[-1].observed_at, 10000, in_stock=False)
    assert ev(make_watch(), 1000, history) == []


# --------------------------------------------------------- below_threshold ----

def test_below_threshold_fires_when_price_crosses():
    watch = make_watch(alert_below_cents=5000)
    assert ev(watch, 4500, flat_history(6000)) == ["below_threshold"]


def test_above_threshold_does_not_fire():
    watch = make_watch(alert_below_cents=5000)
    assert ev(watch, 5500, flat_history(6000)) == []


# CONTRACT CHOICE: price exactly equal to alert_below_cents fires (<=, "target reached").
def test_price_equal_to_threshold_fires():
    watch = make_watch(alert_below_cents=5000)
    assert ev(watch, 5000, flat_history(6000)) == ["below_threshold"]


def test_price_one_cent_over_threshold_does_not_fire():
    assert ev(make_watch(alert_below_cents=5000), 5001, flat_history(6000)) == []


# CONTRACT CHOICE: the very first observation (no history) fires below_threshold if
# already under the target; the other history-based rules cannot fire without history.
def test_first_point_below_threshold_fires():
    assert ev(make_watch(alert_below_cents=5000), 4500, []) == ["below_threshold"]


def test_below_threshold_fires_exactly_once_while_staying_below():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24)
    s = Scheduler(watch, flat_history(6000, 100))
    assert s.observe(step(0), 4500) == ["below_threshold"]
    for i in range(1, 15):  # 30h apart: every check is outside the 24h gap
        assert s.observe(step(i), 4500) == [], f"re-fired on check {i}"
    assert s.count("below_threshold") == 1


def test_price_drifting_lower_while_below_threshold_does_not_refire():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24)
    s = Scheduler(watch, flat_history(6000, 100))
    assert s.observe(step(0), 4500) == ["below_threshold"]
    for i, cents in enumerate([4400, 4300, 4200, 4100, 4000], start=1):
        assert s.observe(step(i), cents) == []
    assert s.count("below_threshold") == 1


def test_below_threshold_once_even_with_all_rules_on_and_flat_afterwards():
    watch = make_watch(**ALL_ON, min_alert_gap_hrs=24)
    s = Scheduler(watch, flat_history(10000, 100))
    first = s.observe(step(0), 5000)
    assert "below_threshold" in first
    for i in range(1, 10):
        assert s.observe(step(i), 5000) == []
    assert s.count("below_threshold") == 1


# --------------------------------------------- recovery debounce (5% rule) ----

def test_recovery_then_redrop_fires_again():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24)
    s = Scheduler(watch, flat_history(6000, 100))
    assert s.observe(step(0), 4500) == ["below_threshold"]
    assert s.observe(step(1), 4500) == []
    assert s.observe(step(2), 5500) == []          # recovered >=5% over 4500 and above threshold
    assert s.observe(step(3), 4600) == ["below_threshold"]
    assert s.count("below_threshold") == 2


def test_small_recovery_then_redrop_does_not_refire():
    # 4500 -> 4700 is +4.4% (< 5%): not a recovery, so the redrop is the same episode.
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24)
    s = Scheduler(watch, flat_history(6000, 100))
    assert s.observe(step(0), 4500) == ["below_threshold"]
    assert s.observe(step(1), 4700) == []
    assert s.observe(step(2), 4400) == []
    assert s.observe(step(3), 4450) == []
    assert s.count("below_threshold") == 1


def test_recovery_must_be_measured_from_the_price_that_triggered():
    # Triggered at 4000; 4150 is +3.75% (no), 4200 is exactly +5% (yes).
    base = dict(alert_below_cents=10000, min_alert_gap_hrs=24)
    alert_at = T0 - days(10)
    watch = make_watch(**base, recent_alerts=(sent(alert_at, "below_threshold", 4000),))

    not_recovered = flat_history(10000, 100)[:-9] + [
        pt(T0 - days(5), 4150), pt(T0 - days(1), 4150)]
    assert ev(watch, 3900, not_recovered) == []

    recovered = flat_history(10000, 100)[:-9] + [
        pt(T0 - days(5), 4200), pt(T0 - days(1), 4000)]
    assert ev(watch, 3900, recovered) == ["below_threshold"]


# CONTRACT CHOICE: recovery counts if ANY observation after the alert was >= 1.05x the
# triggering price (max since sent_at), not only if the immediately previous one was.
def test_recovery_seen_earlier_in_history_still_counts():
    watch = make_watch(alert_below_cents=10000, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - days(10), "below_threshold", 4000),))
    history = flat_history(10000, 100)[:-9] + [
        pt(T0 - days(8), 4000), pt(T0 - days(6), 6000), pt(T0 - days(4), 4100),
        pt(T0 - days(2), 4050)]
    assert ev(watch, 3900, history) == ["below_threshold"]


# CONTRACT CHOICE: only observations AFTER the alert count as recovery; a high price from
# before the alert (the price it dropped from) must not unlock a repeat alert.
def test_pre_alert_prices_do_not_count_as_recovery():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - days(3), "below_threshold", 4500),))
    history = flat_history(9000, 100)[:-3] + [
        pt(T0 - days(3), 4500), pt(T0 - days(2), 4500), pt(T0 - days(1), 4500)]
    assert ev(watch, 4400, history) == []


# CONTRACT CHOICE: debounce is PER REASON: the trigger price comes from the most recent
# alert with the same reason, so an alert of another reason does not suppress this one.
def test_debounce_is_per_reason_not_across_reasons():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - days(3), "pct_drop", 4500),))
    assert ev(watch, 4400, flat_history(6000, 100)) == ["below_threshold"]


# CONTRACT CHOICE: the trigger price is taken from the NEWEST alert of that reason
# (recent_alerts is newest first), not the oldest.
def test_uses_newest_alert_of_the_reason_for_trigger_price():
    # Old alert at 2000 (long recovered since), newest at 4500 and not yet recovered.
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24, recent_alerts=(
        sent(T0 - days(3), "below_threshold", 4500),
        sent(T0 - days(40), "below_threshold", 2000),
    ))
    history = flat_history(6000, 100)[:-3] + [
        pt(T0 - days(3), 4500), pt(T0 - days(2), 4600), pt(T0 - days(1), 4500)]
    assert ev(watch, 4400, history) == []


# CONTRACT CHOICE: new_low and pct_drop obey the same 5% recovery debounce, so successive
# lower lows with no recovery in between alert once.
def test_new_low_repeats_suppressed_until_recovery():
    watch = make_watch(alert_on_new_low=True, min_alert_gap_hrs=24)
    s = Scheduler(watch, flat_history(5000, 100))
    assert s.observe(step(0), 4000) == ["new_low"]
    assert s.observe(step(1), 3900) == []
    assert s.observe(step(2), 3800) == []
    assert s.observe(step(3), 4300) == []   # +7.5% over 4000: recovered
    assert s.observe(step(4), 3700) == ["new_low"]
    assert s.count("new_low") == 2


def test_pct_drop_repeats_suppressed_until_recovery():
    watch = make_watch(alert_pct_drop=Decimal("20"), min_alert_gap_hrs=24)
    s = Scheduler(watch, flat_history(10000, 100))
    assert s.observe(step(0), 7000) == ["pct_drop"]
    assert s.observe(step(1), 7000) == []
    assert s.observe(step(2), 7000) == []
    assert s.count("pct_drop") == 1


# --------------------------------------------------------------- pct_drop -----

def test_pct_drop_fires_at_boundary_and_not_one_cent_above():
    watch = make_watch(alert_pct_drop=Decimal("15.00"))
    history = flat_history(10000, 60)
    assert ev(watch, 8500, history) == ["pct_drop"]      # == median * 0.85 -> fires (<=)
    assert ev(watch, 8501, history) == []


def test_pct_drop_uses_median_not_mean():
    # 29 points at 10000 plus 5 huge outliers: median stays 10000 (threshold 8500)
    # while the mean is ~23500 (a mean-based rule would fire at 9000).
    outliers = [pt(T0 - days(0.1 * k), 100000) for k in range(5, 0, -1)]
    history = flat_history(10000, 29) + outliers
    watch = make_watch(alert_pct_drop=Decimal("15"))
    assert ev(watch, 9000, history) == []
    assert ev(watch, 8500, history) == ["pct_drop"]


def test_pct_drop_ignores_points_older_than_30_days():
    # 40 old points at 2000 would drag the median to 2000 if (wrongly) included.
    old = [pt(T0 - days(d), 2000) for d in range(70, 30, -1)]
    recent = [pt(T0 - days(d), 10000) for d in range(29, 0, -1)]
    watch = make_watch(alert_pct_drop=Decimal("15"))
    assert ev(watch, 8500, old + recent) == ["pct_drop"]


def test_pct_drop_old_high_prices_do_not_inflate_median():
    # 40 old points at 20000 would make the median 20000 (threshold 17000) if included.
    old = [pt(T0 - days(d), 20000) for d in range(70, 30, -1)]
    recent = [pt(T0 - days(d), 10000) for d in range(29, 0, -1)]
    watch = make_watch(alert_pct_drop=Decimal("15"))
    assert ev(watch, 9000, old + recent) == []


# CONTRACT CHOICE: with no points inside the 30-day window there is no median, so
# pct_drop does not fire (rather than falling back to older data).
def test_pct_drop_needs_points_in_window():
    old_only = [pt(T0 - days(d), 10000) for d in range(95, 40, -1)]
    assert ev(make_watch(alert_pct_drop=Decimal("15")), 5000, old_only) == []


def test_pct_drop_without_any_history_does_not_fire():
    assert ev(make_watch(alert_pct_drop=Decimal("15")), 5000, []) == []


def test_pct_drop_accepts_decimal_with_fraction():
    watch = make_watch(alert_pct_drop=Decimal("12.50"))
    history = flat_history(10000, 40)
    assert ev(watch, 8750, history) == ["pct_drop"]
    assert ev(watch, 8751, history) == []


# --------------------------------------------------------------- new_low ------

def test_new_low_fires_below_90_day_minimum():
    watch = make_watch(alert_on_new_low=True)
    assert ev(watch, 4999, flat_history(5000, 100)) == ["new_low"]


def test_new_low_does_not_fire_when_equal_to_minimum():
    assert ev(make_watch(alert_on_new_low=True), 5000, flat_history(5000, 100)) == []


def test_new_low_uses_minimum_inside_window_not_latest_history_point():
    history = [pt(T0 - days(d), 5000) for d in range(89, 1, -1)]
    history[30] = pt(history[30].observed_at, 3000)   # a dip ~60 days ago
    watch = make_watch(alert_on_new_low=True)
    assert ev(watch, 3500, history) == []
    assert ev(watch, 3000, history) == []
    assert ev(watch, 2999, history) == ["new_low"]


def test_new_low_ignores_points_older_than_90_days():
    # A 1000 price 100 days ago is outside the window and must not block this alert.
    history = [pt(T0 - days(100), 1000)] + [pt(T0 - days(d), 5000) for d in range(89, 0, -1)]
    assert ev(make_watch(alert_on_new_low=True), 4000, history) == ["new_low"]


# CONTRACT CHOICE: with no history at all there is no minimum to beat -> no new_low.
def test_new_low_without_history_does_not_fire():
    assert ev(make_watch(alert_on_new_low=True), 4000, []) == []


# CONTRACT CHOICE: points outside 90 days only -> empty window -> no new_low.
def test_new_low_with_only_stale_history_does_not_fire():
    stale = [pt(T0 - days(d), 5000) for d in range(120, 95, -1)]
    assert ev(make_watch(alert_on_new_low=True), 4000, stale) == []


# ------------------------------------------------------------ back_in_stock ---

def _restock_history(prev_in_stock: bool):
    history = flat_history(5000, 10)
    history[-1] = pt(history[-1].observed_at, 5000, in_stock=prev_in_stock)
    return history


def test_back_in_stock_fires_when_previous_point_was_out_of_stock():
    watch = make_watch(alert_on_restock=True)
    assert ev(watch, 5000, _restock_history(False)) == ["back_in_stock"]


def test_back_in_stock_not_when_previous_point_was_in_stock():
    assert ev(make_watch(alert_on_restock=True), 5000, _restock_history(True)) == []


def test_back_in_stock_not_on_first_point_without_history():
    assert ev(make_watch(alert_on_restock=True), 5000, []) == []


def test_back_in_stock_not_when_latest_is_out_of_stock():
    watch = make_watch(alert_on_restock=True)
    assert ev(watch, 5000, _restock_history(False), in_stock=False) == []


def test_back_in_stock_uses_the_immediately_previous_point():
    # Out of stock earlier, but the most recent prior point was already in stock.
    history = flat_history(5000, 10)
    history[-5] = pt(history[-5].observed_at, 5000, in_stock=False)
    assert ev(make_watch(alert_on_restock=True), 5000, history) == []


def test_back_in_stock_fires_regardless_of_price_level():
    # No price rules configured; the restock alone is enough.
    history = _restock_history(False)
    assert ev(make_watch(alert_on_restock=True), 9999, history) == ["back_in_stock"]


# CONTRACT CHOICE: back_in_stock is exempt from the 5%-price-recovery debounce (a restock
# is its own edge trigger); only the gap and mute apply. Two restocks a week apart both fire.
def test_back_in_stock_not_subject_to_price_recovery_debounce():
    watch = make_watch(alert_on_restock=True, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - days(7), "back_in_stock", 5000),))
    assert ev(watch, 5000, _restock_history(False)) == ["back_in_stock"]


# CONTRACT CHOICE: price rules (below_threshold/pct_drop/new_low) never fire on an
# out-of-stock observation - a price you cannot buy at is not actionable.
def test_price_rules_do_not_fire_when_latest_is_out_of_stock():
    watch = make_watch(**ALL_ON)
    history = flat_history(10000, 100)
    assert ev(watch, 4000, history, in_stock=False) == []


# ------------------------------------------------------------------- mute -----

def test_muted_until_in_future_suppresses_everything():
    watch = make_watch(**ALL_ON, muted_until=T0 + hours(1))
    history = flat_history(10000, 100)
    history[-1] = pt(history[-1].observed_at, 10000, in_stock=False)
    assert ev(watch, 1000, history) == []


def test_muted_until_in_past_does_not_suppress():
    watch = make_watch(alert_below_cents=5000, muted_until=T0 - hours(1))
    assert ev(watch, 4500, flat_history(6000)) == ["below_threshold"]


def test_muted_until_none_does_not_suppress():
    assert ev(make_watch(alert_below_cents=5000, muted_until=None), 4500, flat_history(6000)) == [
        "below_threshold"]


# CONTRACT CHOICE: muting suppresses without consuming the alert; if the condition still
# holds once the mute expires, it fires then (nothing was recorded as sent while muted).
def test_alert_fires_after_mute_expires_if_still_below():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24, muted_until=step(2))
    s = Scheduler(watch, flat_history(6000, 100))
    assert s.observe(step(0), 4500) == []
    assert s.observe(step(1), 4500) == []
    assert s.observe(step(3), 4500) == ["below_threshold"]
    assert s.observe(step(4), 4500) == []


# -------------------------------------------------------------------- gap -----

def test_gap_suppresses_second_alert_inside_gap():
    # Same reason, price recovered and dropped again, but the last alert is only 10h old.
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - hours(10), "below_threshold", 4500),))
    history = flat_history(6000, 100)[:-1] + [pt(T0 - hours(5), 6000)]
    assert ev(watch, 4400, history) == []


def test_gap_allows_alert_after_gap_has_elapsed():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - hours(30), "below_threshold", 4500),))
    history = flat_history(6000, 100)[:-1] + [pt(T0 - hours(20), 6000)]
    assert ev(watch, 4400, history) == ["below_threshold"]


# CONTRACT CHOICE: a gap that has elapsed by exactly min_alert_gap_hrs allows the alert (>=).
def test_gap_boundary_exactly_elapsed_allows_alert():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - hours(24), "below_threshold", 4500),))
    history = flat_history(6000, 100)[:-1] + [pt(T0 - hours(12), 6000)]
    assert ev(watch, 4400, history) == ["below_threshold"]


def test_one_minute_inside_gap_still_suppressed():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - hours(24) + hours(1 / 60), "below_threshold", 4500),))
    history = flat_history(6000, 100)[:-1] + [pt(T0 - hours(12), 6000)]
    assert ev(watch, 4400, history) == []


# CONTRACT CHOICE: the gap applies ACROSS reasons - any alert sent inside the gap suppresses
# every reason (a user gets at most one alert burst per gap window).
def test_gap_applies_across_reasons():
    watch = make_watch(alert_on_restock=True, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - hours(2), "pct_drop", 4000),))
    assert ev(watch, 5000, _restock_history(False)) == []


def test_gap_does_not_apply_to_alerts_older_than_gap_of_other_reasons():
    watch = make_watch(alert_on_restock=True, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - hours(48), "pct_drop", 4000),))
    assert ev(watch, 5000, _restock_history(False)) == ["back_in_stock"]


def test_zero_gap_never_suppresses():
    watch = make_watch(alert_on_restock=True, min_alert_gap_hrs=0,
                       recent_alerts=(sent(T0 - hours(0.01), "pct_drop", 4000),))
    assert ev(watch, 5000, _restock_history(False)) == ["back_in_stock"]


def test_gap_uses_most_recent_alert_not_oldest():
    # Newest is 1h old (inside gap) even though an older one is 100h old.
    watch = make_watch(alert_on_restock=True, min_alert_gap_hrs=24, recent_alerts=(
        sent(T0 - hours(1), "below_threshold", 4000),
        sent(T0 - hours(100), "back_in_stock", 5000),
    ))
    assert ev(watch, 5000, _restock_history(False)) == []


# CONTRACT CHOICE: gap suppression is not permanent: a still-true, never-sent condition
# fires on the first check after the gap elapses.
def test_suppressed_by_gap_fires_later_when_gap_elapses():
    watch = make_watch(alert_below_cents=5000, min_alert_gap_hrs=24,
                       recent_alerts=(sent(T0 - hours(10), "back_in_stock", 6000),))
    s = Scheduler(watch, flat_history(6000, 100))
    assert s.observe(T0, 4500) == []                     # inside gap
    assert s.observe(T0 + hours(20), 4500) == ["below_threshold"]   # 30h after the restock alert
    assert s.observe(T0 + hours(50), 4500) == []


# --------------------------------------------------------- rule switches ------

@pytest.mark.parametrize("disabled", sorted(VALID_REASONS))
def test_disabled_rule_never_fires(disabled):
    kwargs = dict(ALL_ON)
    if disabled == "below_threshold":
        kwargs["alert_below_cents"] = None
    elif disabled == "pct_drop":
        kwargs["alert_pct_drop"] = None
    elif disabled == "new_low":
        kwargs["alert_on_new_low"] = False
    else:
        kwargs["alert_on_restock"] = False
    result = ev(make_watch(**kwargs), 5000, _all_conditions_history())
    assert disabled not in result
    assert set(result) == VALID_REASONS - {disabled}


def _all_conditions_history():
    """100 days at 10000, previous point out of stock: a 5000 in-stock latest
    is below 6000, >20% under the median, a new low, and a restock."""
    history = flat_history(10000, 100)
    history[-1] = pt(history[-1].observed_at, 10000, in_stock=False)
    return history


def test_all_four_reasons_fire_together_without_duplicates():
    result = ev(make_watch(**ALL_ON, min_alert_gap_hrs=24), 5000, _all_conditions_history())
    assert isinstance(result, list)
    assert len(result) == len(set(result)) == 4
    assert set(result) == VALID_REASONS


def test_every_returned_reason_is_a_valid_alert_reason_string():
    result = ev(make_watch(**ALL_ON), 5000, _all_conditions_history())
    assert result
    assert all(isinstance(r, str) and r in VALID_REASONS for r in result)


@pytest.mark.parametrize("kwargs", [
    dict(alert_below_cents=None, alert_pct_drop=None, alert_on_new_low=False, alert_on_restock=False),
])
def test_all_rules_off_is_empty_even_if_everything_triggers(kwargs):
    assert ev(make_watch(**kwargs), 1, _all_conditions_history()) == []


def test_alert_below_cents_zero_never_fires_for_positive_prices():
    # A threshold of 0 is a legal (if useless) value; no positive price is below it.
    assert ev(make_watch(alert_below_cents=0), 1, flat_history(5000)) == []


# --------------------------------------------------------------- purity -------

def test_evaluate_does_not_mutate_inputs_and_is_repeatable():
    watch = make_watch(**ALL_ON, min_alert_gap_hrs=24)
    history = _all_conditions_history()
    snapshot = copy.deepcopy(history)
    first = ev(watch, 5000, history)
    second = ev(watch, 5000, history)
    assert first == second and first
    assert history == snapshot
    assert watch.recent_alerts == ()


def test_evaluate_uses_latest_observed_at_as_now_not_wall_clock():
    # Entire scenario is in 2026-06; a wall-clock "now" (years later) would make
    # a mute that ends on 2026-06-01T13:00Z look expired.
    watch = make_watch(alert_below_cents=5000, muted_until=T0 + hours(1))
    assert ev(watch, 4500, flat_history(6000), at=T0) == []
    assert ev(watch, 4500, flat_history(6000, end=T0 + hours(2)), at=T0 + hours(2)) == [
        "below_threshold"]
