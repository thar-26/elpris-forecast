"""Turn a forecast into a decision, and measure what that decision is worth.

A home that can move some of its electricity use, such as charging a battery or
heating water, wants to run it in the cheapest hours of tomorrow. Tomorrow's
prices are not known in the morning, so the hours have to be picked from a forecast.

Four ways of picking the hours are compared. The cost is always counted with
the real prices, whatever was used to pick:

    no_planning        use spread evenly over the day, so it pays the day's average price
    yesterdays_hours   run in the hours that were cheapest yesterday (needs no model)
    forecast_hours     run in the hours the forecast says will be cheapest
    perfect_hours      run in the hours that really were cheapest (only known afterwards)

`perfect_hours` cannot be reached in real life. It is there to show how much room is left.
"""

from __future__ import annotations

import pandas as pd

from .backtest import REFERENCE
from .evaluate import gain_range, verdict
from .forecast import MODEL_NAME

HOURS_NEEDED = 4
MIN_HOURS_IN_DAY = 23  # a day with missing hours is left out, so every plan picks from a full day

NO_PLANNING = "no_planning"
YESTERDAY = "yesterdays_hours"
FORECAST = "forecast_hours"
PERFECT = "perfect_hours"
PLANS = [NO_PLANNING, YESTERDAY, FORECAST, PERFECT]


def cheapest_hours(prices: pd.Series, hours: int = HOURS_NEEDED) -> pd.Index:
    """The index labels of the `hours` lowest prices. When prices tie, the earlier hour wins."""
    if not 1 <= hours <= len(prices):
        raise ValueError(f"Cannot pick {hours} hours from a day with {len(prices)} prices.")
    return prices.sort_values(kind="stable").index[:hours]


def plan_days(
    predictions: pd.DataFrame, hours: int = HOURS_NEEDED, model: str = MODEL_NAME, reference: str = REFERENCE
) -> pd.DataFrame:
    """What each plan really paid, for every zone and test day.

    Input: the output of backtest.walk_forward.
    Output columns: zone, local_date, plan, paid (average real price in the chosen hours, SEK per kWh).
    """
    rows = []
    for (zone, day), group in predictions.groupby(["zone", "local_date"]):
        wide = group.pivot(index="hour_utc", columns="method", values="forecast").sort_index()
        actual = group.drop_duplicates("hour_utc").set_index("hour_utc")["actual"].sort_index()
        if len(actual) < MIN_HOURS_IN_DAY:
            continue
        paid = {
            NO_PLANNING: actual.mean(),
            YESTERDAY: actual[cheapest_hours(wide[reference], hours)].mean(),
            FORECAST: actual[cheapest_hours(wide[model], hours)].mean(),
            PERFECT: actual[cheapest_hours(actual, hours)].mean(),
        }
        rows += [{"zone": zone, "local_date": day, "plan": plan, "paid": float(paid[plan])} for plan in PLANS]
    return pd.DataFrame(rows, columns=["zone", "local_date", "plan", "paid"])


def compare_plans(daily: pd.DataFrame, resamples: int = 5000) -> pd.DataFrame:
    """Average price paid by each plan, per zone.

    Output columns: zone, plan, paid_sek_per_kwh, saving_pct, days_won, days_lost, days, gain_low, gain_high, verdict.

    saving_pct is how much less the plan paid than no planning.
    For forecast_hours, days_won, days_lost, gain_low, gain_high and verdict compare it with
    yesterdays_hours, the same way the models are compared with the baseline. A positive gain means
    the forecast's hours were cheaper. On many days both pick the same hours, so won and lost do not
    add up to all days. If the range includes zero, the verdict is "not proven".
    """
    wide = daily.pivot(index=["zone", "local_date"], columns="plan", values="paid")
    rows = []
    for zone, zone_days in wide.groupby(level="zone"):
        average = zone_days.mean()
        for plan in PLANS:
            row = {
                "zone": zone,
                "plan": plan,
                "paid_sek_per_kwh": round(float(average[plan]), 4),
                "saving_pct": round(float(100 * (average[NO_PLANNING] - average[plan]) / average[NO_PLANNING]), 1)
                if average[NO_PLANNING]
                else 0.0,
                "days_won": None,
                "days_lost": None,
                "days": len(zone_days),
                "gain_low": None,
                "gain_high": None,
                "verdict": "",
            }
            if plan == FORECAST:
                gain = (zone_days[YESTERDAY] - zone_days[FORECAST]).to_numpy()
                low, high = gain_range(gain, resamples)
                row["days_won"] = int((gain > 0).sum())
                row["days_lost"] = int((gain < 0).sum())
                row["gain_low"], row["gain_high"] = round(low, 4), round(high, 4)
                row["verdict"] = verdict(low, high)
            rows.append(row)
    results = pd.DataFrame(rows)
    results[["days_won", "days_lost"]] = results[["days_won", "days_lost"]].astype("Int64")
    return results
