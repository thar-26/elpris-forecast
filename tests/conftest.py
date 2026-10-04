"""Shared test helpers.

The tests never call the real API. They use made-up prices in the same shape
the API returns, so they run fast, offline, and give the same result every time.
"""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

STOCKHOLM_SUMMER = timezone(timedelta(hours=2))


def make_raw_day(day: date, step_minutes: int = 15, base_price: float = 0.50) -> list[dict]:
    """Build one day of fake API records. Hour h costs base_price + h/100 SEK per kWh."""
    start = datetime(day.year, day.month, day.day, tzinfo=STOCKHOLM_SUMMER)
    records = []
    for index in range(24 * 60 // step_minutes):
        begin = start + timedelta(minutes=index * step_minutes)
        sek = round(base_price + begin.hour / 100, 5)
        records.append(
            {
                "SEK_per_kWh": sek,
                "EUR_per_kWh": round(sek / 11.0, 5),
                "EXR": 11.0,
                "time_start": begin.isoformat(),
                "time_end": (begin + timedelta(minutes=step_minutes)).isoformat(),
            }
        )
    return records


@pytest.fixture
def raw_day():
    return make_raw_day


@pytest.fixture
def hourly_prices():
    """Ten days of hourly prices for one zone, rising by 0.01 each hour."""
    hours = pd.date_range("2026-09-01", periods=240, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "zone": "SE3",
            "hour_utc": hours,
            "sek_per_kwh": [round(index * 0.01, 2) for index in range(240)],
            "eur_per_kwh": 0.0,
        }
    )
