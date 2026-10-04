from datetime import date, datetime, timezone

import pandas as pd
import pytest

from elpris import forecast, record

DAY = date(2026, 7, 20)
MADE_AT = datetime(2026, 7, 19, 5, 17, tzinfo=timezone.utc)


@pytest.fixture
def day_forecast(long_prices):
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    return forecast.forecast_day(known, DAY)


def test_forecasts_are_written_with_model_and_time(tmp_path, day_forecast):
    added = record.add_forecasts(tmp_path, day_forecast, model="ridge", made_at=MADE_AT)
    stored = record.read_forecasts(tmp_path)
    assert added == 48
    assert list(stored.columns) == record.FORECAST_COLUMNS
    assert set(stored["model"]) == {"ridge"}
    assert set(stored["made_at_utc"]) == {"2026-07-19T05:17:00Z"}


def test_a_recorded_forecast_is_never_overwritten(tmp_path, day_forecast):
    record.add_forecasts(tmp_path, day_forecast, model="ridge", made_at=MADE_AT)
    changed = day_forecast.assign(forecast_sek_per_kwh=99.0)
    assert record.add_forecasts(tmp_path, changed, model="cheat") == 0
    stored = record.read_forecasts(tmp_path)
    assert len(stored) == 48
    assert stored["forecast_sek_per_kwh"].max() < 99
    assert set(stored["model"]) == {"ridge"}


def test_a_day_is_not_scored_before_its_real_prices_arrive(tmp_path, long_prices, day_forecast):
    record.add_forecasts(tmp_path, day_forecast, model="ridge", made_at=MADE_AT)
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    assert record.score_pending(tmp_path, known).empty
    assert record.read_scores(tmp_path).empty


def test_scoring_uses_the_real_prices_and_happens_only_once(tmp_path, long_prices, day_forecast):
    record.add_forecasts(tmp_path, day_forecast, model="ridge", made_at=MADE_AT)
    new = record.score_pending(tmp_path, long_prices)
    assert len(new) == 2 and set(new["hours"]) == {24}

    # check one zone by hand
    se3 = day_forecast[day_forecast["zone"] == "SE3"].merge(long_prices, on=["zone", "hour_utc"])
    expected = (se3["sek_per_kwh"] - se3["forecast_sek_per_kwh"]).abs().mean()
    assert new.set_index("zone").loc["SE3", "mae_model"] == pytest.approx(expected, abs=1e-4)

    assert record.score_pending(tmp_path, long_prices).empty
    assert len(record.read_scores(tmp_path)) == 2


def test_model_won_flag_matches_the_two_errors(tmp_path):
    hours = pd.date_range("2026-07-19 22:00", periods=24, freq="h", tz="UTC")
    forecasts = pd.DataFrame(
        {
            "delivery_date": "2026-07-20",
            "zone": "SE3",
            "hour_utc": hours,
            "forecast_sek_per_kwh": 1.10,   # misses by 0.10
            "baseline_sek_per_kwh": 0.70,   # misses by 0.30
        }
    )
    prices = pd.DataFrame({"zone": "SE3", "hour_utc": hours, "sek_per_kwh": 1.00})
    record.add_forecasts(tmp_path, forecasts, model="ridge", made_at=MADE_AT)
    row = record.score_pending(tmp_path, prices).iloc[0]
    assert row["mae_model"] == pytest.approx(0.10)
    assert row["mae_baseline"] == pytest.approx(0.30)
    assert row["model_won"] == 1


def test_summary_page_says_so_when_nothing_is_scored_yet(tmp_path, day_forecast):
    record.add_forecasts(tmp_path, day_forecast, model="ridge", made_at=MADE_AT)
    text = record.write_summary(tmp_path).read_text(encoding="utf-8")
    assert "No days scored yet" in text
    assert "1 day(s)" in text


def test_summary_page_shows_totals_once_days_are_scored(tmp_path, long_prices, day_forecast):
    record.add_forecasts(tmp_path, day_forecast, model="ridge", made_at=MADE_AT)
    record.score_pending(tmp_path, long_prices)
    text = record.write_summary(tmp_path).read_text(encoding="utf-8")
    assert "## Totals since 2026-07-20" in text
    assert "| SE3 | 1 |" in text
    assert "not proven" in text  # one day can never prove anything
