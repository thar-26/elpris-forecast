"""Turn stored prices into model inputs, without ever looking at the future.

The forecast for tomorrow is made today, when prices up to the end of today are known.
So every input for an hour is at least 24 hours older than that hour.
That one rule is what keeps the test honest, and tests/test_features.py checks it.
"""

from __future__ import annotations

import pandas as pd

LOCAL_TIMEZONE = "Europe/Stockholm"

FEATURES = [
    "lag_24",    # price at the same hour yesterday
    "lag_48",    # price at the same hour two days ago
    "lag_168",   # price at the same hour last week
    "mean_24",   # average of the 24 hours ending 24 hours ago
    "std_24",    # how much prices moved in those 24 hours
    "mean_168",  # average of the week ending 24 hours ago
    "hour",      # hour of the day, Swedish time
    "weekend",   # 1 on Saturday and Sunday
]


def build_features(prices: pd.DataFrame, until: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per zone and hour, with the actual price and the inputs for that hour.

    Input columns: zone, hour_utc, sek_per_kwh.
    Output columns: zone, hour_utc, local_date, actual, plus everything in FEATURES.
    Hours without a full week of history behind them are dropped.

    `until` adds rows for future hours up to that time. Their `actual` is empty,
    but their inputs are built by exactly the same code as the training rows.
    """
    frames = []
    for zone, group in prices.groupby("zone"):
        series = group.set_index("hour_utc")["sek_per_kwh"].sort_index().asfreq("h")
        if until is not None and until > series.index.max():
            series = series.reindex(pd.date_range(series.index.min(), until, freq="h"))
            series.index.name = "hour_utc"
        known = series.shift(24)  # the newest price we are allowed to use for each hour

        frame = pd.DataFrame({"actual": series})
        frame["lag_24"] = known
        frame["lag_48"] = series.shift(48)
        frame["lag_168"] = series.shift(168)
        frame["mean_24"] = known.rolling(24).mean()
        frame["std_24"] = known.rolling(24).std()
        frame["mean_168"] = known.rolling(168).mean()

        local = frame.index.tz_convert(LOCAL_TIMEZONE)
        frame["hour"] = local.hour
        frame["weekend"] = (local.dayofweek >= 5).astype(int)
        frame["local_date"] = local.date
        frame["zone"] = zone
        frames.append(frame.reset_index())

    columns = ["zone", "hour_utc", "local_date", "actual", *FEATURES]
    if not frames:
        return pd.DataFrame(columns=columns)
    result = pd.concat(frames, ignore_index=True)[columns].dropna(subset=FEATURES)
    if until is None:
        result = result.dropna(subset=["actual"])
    return result.reset_index(drop=True)
