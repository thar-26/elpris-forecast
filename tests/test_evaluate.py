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


def _predictions(days, reference_miss, model_miss):
    """Build a tiny walk-forward result: one hour per day, with chosen misses."""
    rows = []
    for index, day in enumerate(days):
        for method, miss in (("same_hour_yesterday", reference_miss[index]), ("model", model_miss[index])):
            rows.append({"zone": "SE3", "local_date": day, "method": method, "actual": 1.0, "forecast": 1.0 + miss})
    return pd.DataFrame(rows)


def test_compare_methods_reports_a_clear_win():
    from elpris.evaluate import compare_methods

    days = [f"2026-09-{d:02d}" for d in range(1, 11)]
    predictions = _predictions(days, reference_miss=[0.40] * 10, model_miss=[0.30] * 10)
    results = compare_methods(predictions, reference="same_hour_yesterday").set_index("method")

    assert results.loc["same_hour_yesterday", "verdict"] == "reference"
    assert results.loc["model", "mae_sek_per_kwh"] == pytest.approx(0.30)
    assert results.loc["model", "gain_pct"] == pytest.approx(25.0)
    assert results.loc["model", "days_won"] == 10
    assert results.loc["model", "verdict"] == "beats baseline"


def test_compare_methods_reports_a_clear_loss():
    from elpris.evaluate import compare_methods

    days = [f"2026-09-{d:02d}" for d in range(1, 11)]
    predictions = _predictions(days, reference_miss=[0.30] * 10, model_miss=[0.45] * 10)
    results = compare_methods(predictions, reference="same_hour_yesterday").set_index("method")
    assert results.loc["model", "verdict"] == "worse"
    assert results.loc["model", "days_won"] == 0


def test_compare_methods_says_not_proven_when_wins_and_losses_cancel():
    from elpris.evaluate import compare_methods

    days = [f"2026-09-{d:02d}" for d in range(1, 11)]
    predictions = _predictions(days, reference_miss=[0.40] * 10, model_miss=[0.10, 0.70] * 5)
    results = compare_methods(predictions, reference="same_hour_yesterday").set_index("method")
    assert results.loc["model", "verdict"] == "not proven"
    assert results.loc["model", "days_won"] == 5
