from datetime import date

import pandas as pd
import pytest

from elpris import forecast
from elpris.features import FEATURES, build_features

DAY = date(2026, 7, 20)


def test_a_normal_day_has_24_hours_starting_at_swedish_midnight():
    hours = forecast.delivery_hours(DAY)
    assert len(hours) == 24
    assert str(hours[0]) == "2026-07-19 22:00:00+00:00"


def test_clock_change_days_have_23_and_25_hours():
    assert len(forecast.delivery_hours(date(2026, 3, 29))) == 23
    assert len(forecast.delivery_hours(date(2026, 10, 25))) == 25


def test_forecast_covers_every_hour_of_the_day_for_every_zone(long_prices):
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    result = forecast.forecast_day(known, DAY)
    assert list(result.columns) == [
        "delivery_date", "zone", "hour_utc", "forecast_sek_per_kwh", "baseline_sek_per_kwh",
    ]
    assert result.groupby("zone").size().to_dict() == {"SE3": 24, "SE4": 24}
    assert set(result["delivery_date"]) == {"2026-07-20"}
    assert not result.isna().any().any()


def test_forecast_is_the_same_whether_or_not_the_answer_is_already_stored(long_prices):
    """If the real prices for the delivery day are in the database, they must be ignored."""
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    without_answer = forecast.forecast_day(known, DAY)
    with_answer = forecast.forecast_day(long_prices, DAY)
    pd.testing.assert_frame_equal(without_answer, with_answer)


def test_baseline_column_is_the_price_24_hours_earlier(long_prices):
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    result = forecast.forecast_day(known, DAY)
    row = result[result["zone"] == "SE3"].iloc[5]
    earlier = known[(known["zone"] == "SE3") & (known["hour_utc"] == row["hour_utc"] - pd.Timedelta(hours=24))]
    assert row["baseline_sek_per_kwh"] == pytest.approx(earlier["sek_per_kwh"].item(), abs=1e-5)


def test_inputs_for_future_hours_match_what_they_are_once_prices_arrive(long_prices):
    """The model must be fed the same numbers in live use as in the backtest."""
    hours = forecast.delivery_hours(DAY)
    known = long_prices[long_prices["hour_utc"] < hours[0]]
    live = build_features(known, until=hours[-1])
    live = live[live["hour_utc"].isin(hours)].reset_index(drop=True)
    later = build_features(long_prices)
    later = later[later["hour_utc"].isin(hours)].reset_index(drop=True)
    pd.testing.assert_frame_equal(live[FEATURES], later[FEATURES])
    assert live["actual"].isna().all()


def test_missing_prices_for_the_day_before_give_a_clear_error(long_prices):
    hours = forecast.delivery_hours(DAY)
    stale = long_prices[long_prices["hour_utc"] < hours[0] - pd.Timedelta(hours=30)]
    with pytest.raises(ValueError, match="missing or incomplete"):
        forecast.forecast_day(stale, DAY)


def test_too_little_history_gives_a_clear_error(long_prices):
    with pytest.raises(ValueError, match="not enough history"):
        forecast.forecast_day(long_prices.iloc[: 24 * 12], date(2026, 6, 13))


def test_too_late_starts_at_noon_swedish_time_the_day_before():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from elpris.forecast import too_late

    sweden = ZoneInfo("Europe/Stockholm")
    day = date(2026, 10, 6)
    assert not too_late(day, datetime(2026, 10, 5, 11, 59, tzinfo=sweden))
    assert too_late(day, datetime(2026, 10, 5, 12, 0, tzinfo=sweden))
    assert not too_late(day, datetime(2026, 10, 4, 23, 0, tzinfo=sweden))
    # the same moment given in UTC: 10:30 UTC is 12:30 in Sweden in summer time
    assert too_late(day, datetime(2026, 10, 5, 10, 30, tzinfo=timezone.utc))
    assert not too_late(day, datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc))
    # in winter time Sweden is one hour ahead of UTC, so 10:30 UTC is still before noon
    assert not too_late(date(2026, 12, 2), datetime(2026, 12, 1, 10, 30, tzinfo=timezone.utc))
