"""Score forecasts against what really happened.

The score is mean absolute error (MAE): the average size of the miss, in SEK per kWh.
Percentage errors are avoided on purpose, because prices can be zero or negative.
"""

from __future__ import annotations

import pandas as pd

from .baseline import BASELINES, naive_forecast


def mean_absolute_error(actual: pd.Series, forecast: pd.Series) -> float:
    return float((actual - forecast).abs().mean())


def backtest_baselines(prices: pd.DataFrame) -> pd.DataFrame:
    """Score every baseline on the same hours, so the comparison is fair.

    Input columns: zone, hour_utc, sek_per_kwh.
    Output columns: zone, baseline, hours_scored, mae_sek_per_kwh.
    """
    scored = prices[["zone", "hour_utc", "sek_per_kwh"]].copy()
    for name, lag in BASELINES.items():
        forecast = naive_forecast(prices, lag).rename(columns={"forecast_sek_per_kwh": name})
        scored = scored.merge(forecast, on=["zone", "hour_utc"], how="inner")

    rows = []
    for zone, group in scored.groupby("zone"):
        for name in BASELINES:
            rows.append(
                {
                    "zone": zone,
                    "baseline": name,
                    "hours_scored": len(group),
                    "mae_sek_per_kwh": round(mean_absolute_error(group["sek_per_kwh"], group[name]), 4),
                }
            )
    return pd.DataFrame(rows, columns=["zone", "baseline", "hours_scored", "mae_sek_per_kwh"])
