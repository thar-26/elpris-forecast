import pandas as pd
import pytest

from elpris.evaluate import backtest_baselines, mean_absolute_error


def test_mean_absolute_error_on_a_known_example():
    actual = pd.Series([1.0, 2.0, 3.0])
    forecast = pd.Series([1.5, 2.0, 1.0])
    assert mean_absolute_error(actual, forecast) == pytest.approx((0.5 + 0.0 + 2.0) / 3)


def test_backtest_scores_on_known_data(hourly_prices):
    results = backtest_baselines(hourly_prices).set_index("baseline")
    # prices rise 0.01 per hour, so the miss is exactly lag * 0.01
    assert results.loc["same_hour_yesterday", "mae_sek_per_kwh"] == pytest.approx(0.24)
    assert results.loc["same_hour_last_week", "mae_sek_per_kwh"] == pytest.approx(1.68)


def test_all_baselines_are_scored_on_the_same_hours(hourly_prices):
    results = backtest_baselines(hourly_prices)
    # 240 hours of history minus the 168 hours the weekly baseline needs
    assert set(results["hours_scored"]) == {240 - 168}


def test_too_little_history_gives_an_empty_result(hourly_prices):
    assert backtest_baselines(hourly_prices.head(48)).empty
