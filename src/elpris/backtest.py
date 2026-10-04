"""Walk-forward test: replay the past one day at a time.

For each test day, every model is trained only on days before it and then
forecasts that day. This copies how the system will run for real, where
tomorrow is always unseen.
"""

from __future__ import annotations

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from .features import FEATURES

REFERENCE = "same_hour_yesterday"
MIN_TRAINING_DAYS = 14


def make_models() -> dict:
    """The models to compare. Each entry builds a fresh, untrained model."""
    return {
        "ridge": lambda: Ridge(alpha=1.0),
        "boosting": lambda: HistGradientBoostingRegressor(
            max_depth=3, max_iter=150, learning_rate=0.05, random_state=0
        ),
    }


def split_day(rows: pd.DataFrame, day) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Training rows are strictly before `day`. Test rows are `day` itself."""
    return rows[rows["local_date"] < day], rows[rows["local_date"] == day]


def walk_forward(features: pd.DataFrame, test_days: int = 28) -> pd.DataFrame:
    """Forecast each of the last `test_days` days using only earlier days.

    Returns one row per zone, hour and method.
    Columns: zone, hour_utc, local_date, method, actual, forecast.
    """
    all_days = sorted(features["local_date"].unique())
    if len(all_days) < test_days + MIN_TRAINING_DAYS:
        raise ValueError(
            f"Need at least {test_days + MIN_TRAINING_DAYS} usable days "
            f"({MIN_TRAINING_DAYS} to train, {test_days} to test), have {len(all_days)}. "
            "Download more history or lower --test-days."
        )
    days_to_test = all_days[-test_days:]
    models = make_models()
    pieces = []

    for zone, zone_rows in features.groupby("zone"):
        for day in days_to_test:
            train, test = split_day(zone_rows, day)
            if test.empty:
                continue

            forecasts = {
                REFERENCE: test["lag_24"].to_numpy(),
                "blend_yesterday_and_week": (0.5 * test["lag_24"] + 0.5 * test["mean_168"]).to_numpy(),
            }
            for name, build in models.items():
                model = build().fit(train[FEATURES], train["actual"])
                forecasts[name] = model.predict(test[FEATURES])

            for method, values in forecasts.items():
                piece = test[["zone", "hour_utc", "local_date", "actual"]].copy()
                piece["method"] = method
                piece["forecast"] = values
                pieces.append(piece)

    columns = ["zone", "hour_utc", "local_date", "method", "actual", "forecast"]
    return pd.concat(pieces, ignore_index=True)[columns]
