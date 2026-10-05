import pandas as pd
import pytest

from elpris import backtest, schedule
from elpris.features import build_features


def test_cheapest_hours_picks_the_lowest_prices():
    prices = pd.Series([5.0, 1.0, 4.0, 2.0, 3.0], index=list("abcde"))
    assert list(schedule.cheapest_hours(prices, 2)) == ["b", "d"]


def test_when_prices_tie_the_earlier_hour_wins():
    prices = pd.Series([2.0, 1.0, 1.0, 1.0], index=[0, 1, 2, 3])
    assert list(schedule.cheapest_hours(prices, 2)) == [1, 2]


def test_asking_for_more_hours_than_the_day_has_fails_clearly():
    with pytest.raises(ValueError, match="Cannot pick 5 hours"):
        schedule.cheapest_hours(pd.Series([1.0, 2.0]), 5)


def one_day(actual, model, yesterday):
    """A hand-made day for one zone, in the shape walk_forward returns."""
    hours = pd.date_range("2026-07-20", periods=len(actual), freq="h", tz="UTC")
    pieces = []
    for method, values in (("ridge", model), ("same_hour_yesterday", yesterday)):
        pieces.append(
            pd.DataFrame(
                {"zone": "SE3", "hour_utc": hours, "local_date": "2026-07-20", "method": method,
                 "actual": actual, "forecast": values}
            )
        )
    return pd.concat(pieces, ignore_index=True)


def test_every_plan_is_charged_the_real_price_of_the_hours_it_chose():
    # 24 hours. Real prices: hour h costs h, so the two cheapest hours are 0 and 1.
    actual = [float(h) for h in range(24)]
    model = actual[::-1]                 # the model has it backwards: it picks hours 23 and 22
    yesterday = actual                   # yesterday's prices point at the right hours
    daily = schedule.plan_days(one_day(actual, model, yesterday), hours=2)
    paid = daily.set_index("plan")["paid"]

    assert paid[schedule.NO_PLANNING] == pytest.approx(11.5)   # average of 0..23
    assert paid[schedule.PERFECT] == pytest.approx(0.5)        # hours 0 and 1
    assert paid[schedule.YESTERDAY] == pytest.approx(0.5)
    assert paid[schedule.FORECAST] == pytest.approx(22.5)      # hours 23 and 22, at their real price


def test_a_day_with_missing_hours_is_left_out():
    short = [1.0] * 10
    assert schedule.plan_days(one_day(short, short, short), hours=2).empty


def test_no_plan_can_beat_perfect_hindsight(long_prices):
    predictions = backtest.walk_forward(build_features(long_prices), test_days=10)
    daily = schedule.plan_days(predictions, hours=4)
    wide = daily.pivot(index=["zone", "local_date"], columns="plan", values="paid")
    assert len(wide) >= 2 * 9   # the last day of the made-up prices is cut short, so it is left out
    for plan in (schedule.NO_PLANNING, schedule.YESTERDAY, schedule.FORECAST):
        assert (wide[schedule.PERFECT] <= wide[plan] + 1e-12).all()


def test_comparison_has_one_row_per_zone_and_plan(long_prices):
    predictions = backtest.walk_forward(build_features(long_prices), test_days=10)
    results = schedule.compare_plans(schedule.plan_days(predictions, hours=4), resamples=200)
    assert len(results) == 2 * len(schedule.PLANS)
    assert set(results["days"]) == {9}   # 10 test days, minus the last one, which is cut short

    no_planning = results[results["plan"] == schedule.NO_PLANNING]
    assert set(no_planning["saving_pct"]) == {0.0}

    forecast_rows = results[results["plan"] == schedule.FORECAST]
    assert set(forecast_rows["verdict"]) <= {"beats baseline", "not proven", "worse"}
    assert forecast_rows["gain_low"].notna().all()
    assert ((forecast_rows["days_won"] + forecast_rows["days_lost"]) <= forecast_rows["days"]).all()
    # only the forecast plan is given a verdict
    assert set(results[results["plan"] != schedule.FORECAST]["verdict"]) == {""}
