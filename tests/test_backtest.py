import pytest

from elpris import backtest
from elpris.evaluate import compare_methods
from elpris.features import build_features


def test_training_rows_are_always_before_the_test_day(long_prices):
    features = build_features(long_prices)
    zone_rows = features[features["zone"] == "SE3"]
    day = sorted(zone_rows["local_date"].unique())[30]
    train, test = backtest.split_day(zone_rows, day)
    assert train["local_date"].max() < day
    assert set(test["local_date"]) == {day}


def test_walk_forward_returns_every_method_for_every_test_hour(long_prices):
    predictions = backtest.walk_forward(build_features(long_prices), test_days=5)
    assert set(predictions["method"]) == {"same_hour_yesterday", "blend_yesterday_and_week", "ridge", "boosting"}
    assert predictions["local_date"].nunique() == 5
    counts = predictions.groupby("method").size()
    assert counts.nunique() == 1  # every method is scored on exactly the same hours


def test_reference_forecast_is_yesterdays_price(long_prices):
    features = build_features(long_prices)
    predictions = backtest.walk_forward(features, test_days=3)
    reference = predictions[predictions["method"] == backtest.REFERENCE]
    merged = reference.merge(features[["zone", "hour_utc", "lag_24"]], on=["zone", "hour_utc"])
    assert (merged["forecast"] == merged["lag_24"]).all()


def test_too_little_history_gives_a_clear_error(long_prices):
    features = build_features(long_prices)
    with pytest.raises(ValueError, match="Download more history"):
        backtest.walk_forward(features, test_days=500)


def test_a_model_beats_yesterday_when_yesterday_is_a_poor_guide(long_prices):
    """In the made-up data each day's level is random, so copying yesterday is a bad forecast."""
    predictions = backtest.walk_forward(build_features(long_prices), test_days=20)
    results = compare_methods(predictions, reference=backtest.REFERENCE)
    ridge = results[results["method"] == "ridge"]
    assert (ridge["gain_pct"] > 0).all()
