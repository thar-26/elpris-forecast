import pandas as pd

from elpris.features import FEATURES, build_features


def test_output_has_the_expected_columns_and_no_gaps(long_prices):
    features = build_features(long_prices)
    assert list(features.columns) == ["zone", "hour_utc", "local_date", "actual", *FEATURES]
    assert not features.isna().any().any()
    assert set(features["zone"]) == {"SE3", "SE4"}


def test_lag_24_is_the_actual_price_24_hours_earlier(long_prices):
    features = build_features(long_prices)
    zone = features[features["zone"] == "SE3"].set_index("hour_utc")
    hour = zone.index[100]
    assert zone.loc[hour, "lag_24"] == zone.loc[hour - pd.Timedelta(hours=24), "actual"]


def test_first_usable_hour_has_a_full_week_of_history(long_prices):
    features = build_features(long_prices)
    start = long_prices["hour_utc"].min()
    # mean_168 needs 168 hours ending 24 hours before the target hour
    assert features["hour_utc"].min() == start + pd.Timedelta(hours=24 + 167)


def test_inputs_never_use_prices_newer_than_24_hours_before(long_prices):
    """The most important test in the project.

    Change every price after a cut-off. The inputs for any hour up to
    24 hours after the cut-off must stay exactly the same. If they change,
    the model is being shown information it would not have in real use.
    """
    cutoff = pd.Timestamp("2026-07-10 12:00", tz="UTC")
    changed = long_prices.copy()
    changed.loc[changed["hour_utc"] > cutoff, "sek_per_kwh"] = 999.0

    before = build_features(long_prices)
    after = build_features(changed)

    safe_until = cutoff + pd.Timedelta(hours=24)
    before_safe = before[before["hour_utc"] <= safe_until].reset_index(drop=True)
    after_safe = after[after["hour_utc"] <= safe_until].reset_index(drop=True)
    pd.testing.assert_frame_equal(before_safe[FEATURES], after_safe[FEATURES])

    # and the check is not empty: hours after that point do change
    assert not before[before["hour_utc"] > safe_until][FEATURES].reset_index(drop=True).equals(
        after[after["hour_utc"] > safe_until][FEATURES].reset_index(drop=True)
    )


def test_hour_and_weekend_use_swedish_time(long_prices):
    features = build_features(long_prices)
    # Saturday 11 July 2026, 22:30 UTC is already Sunday 00:30 in Sweden
    row = features[(features["zone"] == "SE3") & (features["hour_utc"] == pd.Timestamp("2026-07-11 22:00", tz="UTC"))]
    assert row["hour"].item() == 0
    assert row["weekend"].item() == 1
    assert str(row["local_date"].item()) == "2026-07-12"
    # Sunday 22:00 UTC is Monday 00:00 in Sweden, so not a weekend
    monday = features[(features["zone"] == "SE3") & (features["hour_utc"] == pd.Timestamp("2026-07-12 22:00", tz="UTC"))]
    assert monday["weekend"].item() == 0


def test_missing_hours_drop_the_rows_that_depend_on_them(long_prices):
    hole = pd.Timestamp("2026-07-01 05:00", tz="UTC")
    with_hole = long_prices[long_prices["hour_utc"] != hole]
    features = build_features(with_hole)
    se3 = features[features["zone"] == "SE3"]
    assert hole not in set(se3["hour_utc"])
    assert hole + pd.Timedelta(hours=24) not in set(se3["hour_utc"])  # its lag_24 is missing
    assert not features.isna().any().any()


def test_empty_input_gives_empty_output():
    empty = pd.DataFrame(columns=["zone", "hour_utc", "sek_per_kwh"])
    assert build_features(empty).empty
