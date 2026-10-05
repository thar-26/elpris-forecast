"""Make the real forecast for one delivery day.

The model is trained on every day before the delivery day and nothing else.
If prices for the delivery day happen to be stored already, they are ignored.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .backtest import MIN_TRAINING_DAYS, make_models
from .features import FEATURES, LOCAL_TIMEZONE, build_features

MODEL_NAME = "ridge"

# Real prices for a day come out around 12:45 to 13:00 Swedish time the day before.
# A forecast made after this hour could be suspected of having seen them, so it is not recorded.
CUTOFF_HOUR = 12


def too_late(day: date, now: datetime) -> bool:
    """True once the real prices for `day` may already be public. `now` must carry a time zone."""
    cutoff = datetime.combine(day - timedelta(days=1), time(CUTOFF_HOUR), tzinfo=ZoneInfo(LOCAL_TIMEZONE))
    return now >= cutoff


def delivery_hours(day: date) -> pd.DatetimeIndex:
    """The hours of one Swedish calendar day, in UTC. 23 or 25 hours on clock-change days."""
    start = pd.Timestamp(day).tz_localize(LOCAL_TIMEZONE)
    end = (pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(LOCAL_TIMEZONE)
    return pd.date_range(start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h", inclusive="left")


def forecast_day(prices: pd.DataFrame, day: date) -> pd.DataFrame:
    """Forecast every hour of `day` for every zone.

    Input columns: zone, hour_utc, sek_per_kwh.
    Output columns: delivery_date, zone, hour_utc, forecast_sek_per_kwh, baseline_sek_per_kwh.
    The baseline is the price at the same hour the day before.
    """
    hours = delivery_hours(day)
    rows = build_features(prices, until=hours[-1])
    pieces = []

    for zone, zone_rows in rows.groupby("zone"):
        train = zone_rows[zone_rows["actual"].notna() & (zone_rows["local_date"] < day)]
        target = zone_rows[zone_rows["hour_utc"].isin(hours)]

        if len(train) < MIN_TRAINING_DAYS * 24:
            raise ValueError(f"{zone}: not enough history to train. Run a backfill first.")
        if len(target) != len(hours):
            raise ValueError(
                f"{zone}: inputs are ready for {len(target)} of {len(hours)} hours on {day}. "
                "The prices for the day before are missing or incomplete."
            )

        model = make_models()[MODEL_NAME]().fit(train[FEATURES], train["actual"])
        pieces.append(
            pd.DataFrame(
                {
                    "delivery_date": day.isoformat(),
                    "zone": zone,
                    "hour_utc": target["hour_utc"].to_numpy(),
                    "forecast_sek_per_kwh": model.predict(target[FEATURES]).round(5),
                    "baseline_sek_per_kwh": target["lag_24"].to_numpy().round(5),
                }
            )
        )

    if not pieces:
        raise ValueError("No prices stored yet. Run a backfill first.")
    return pd.concat(pieces, ignore_index=True)
