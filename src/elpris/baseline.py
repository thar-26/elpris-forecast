"""Simple forecasts that any real model has to beat.

A baseline uses no machine learning. It just repeats a past price.
If a model cannot beat these, the model is not worth running.
"""

from __future__ import annotations

import pandas as pd

# name -> how many hours back to copy the price from
BASELINES = {
    "same_hour_yesterday": 24,
    "same_hour_last_week": 168,
}


def naive_forecast(prices: pd.DataFrame, lag_hours: int) -> pd.DataFrame:
    """Forecast each hour as the price `lag_hours` earlier in the same zone.

    Input columns: zone, hour_utc, sek_per_kwh.
    Output columns: zone, hour_utc, forecast_sek_per_kwh.
    """
    if lag_hours <= 0:
        raise ValueError("lag_hours must be positive.")
    forecast = prices[["zone", "hour_utc", "sek_per_kwh"]].copy()
    forecast["hour_utc"] = forecast["hour_utc"] + pd.Timedelta(hours=lag_hours)
    return forecast.rename(columns={"sek_per_kwh": "forecast_sek_per_kwh"})
