"""Score forecasts against what really happened.

The score is mean absolute error (MAE): the average size of the miss, in SEK per kWh.
Percentage errors are avoided on purpose, because prices can be zero or negative.
"""

from __future__ import annotations

import numpy as np
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


def compare_methods(predictions: pd.DataFrame, reference: str, resamples: int = 5000) -> pd.DataFrame:
    """Compare every method with the reference method, day by day.

    Input: the output of backtest.walk_forward.
    Output columns: zone, method, mae_sek_per_kwh, gain_pct, days_won, days, gain_low, gain_high, verdict.

    gain_pct is how much lower the error is than the reference. Positive is better.
    gain_low and gain_high give a 95% range for the average daily gain in SEK per kWh.
    It is found by resampling the test days. If the range includes zero,
    the win could be luck, and the verdict says "not proven".
    """
    scored = predictions.assign(miss=(predictions["actual"] - predictions["forecast"]).abs())
    daily = scored.groupby(["zone", "method", "local_date"])["miss"].mean().unstack("method")
    overall = scored.groupby(["zone", "method"])["miss"].mean()
    random = np.random.default_rng(0)

    rows = []
    for zone, zone_daily in daily.groupby(level="zone"):
        reference_mae = overall[(zone, reference)]
        for method in zone_daily.columns:
            mae = overall[(zone, method)]
            row = {
                "zone": zone,
                "method": method,
                "mae_sek_per_kwh": round(float(mae), 4),
                "gain_pct": round(float(100 * (reference_mae - mae) / reference_mae), 1),
                "days_won": None,
                "days": len(zone_daily),
                "gain_low": None,
                "gain_high": None,
                "verdict": "reference",
            }
            if method != reference:
                gain = (zone_daily[reference] - zone_daily[method]).to_numpy()
                samples = random.choice(gain, size=(resamples, len(gain))).mean(axis=1)
                low, high = np.percentile(samples, [2.5, 97.5])
                row["days_won"] = int((gain > 0).sum())
                row["gain_low"] = round(float(low), 4)
                row["gain_high"] = round(float(high), 4)
                row["verdict"] = "beats baseline" if low > 0 else ("worse" if high < 0 else "not proven")
            rows.append(row)

    results = pd.DataFrame(rows)
    results["days_won"] = results["days_won"].astype("Int64")
    # reference first in each zone, then best method first
    results["is_model"] = results["method"] != reference
    results = results.sort_values(["zone", "is_model", "mae_sek_per_kwh"]).drop(columns="is_model")
    return results.reset_index(drop=True)
