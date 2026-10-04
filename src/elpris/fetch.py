"""Download one day of prices for one zone, check it, and return hourly rows.

The API gives either 24 hourly prices or 96 quarter-hour prices per day.
Both are turned into hourly averages so the rest of the project sees one shape.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd
import requests

from . import config

REQUIRED_FIELDS = {"SEK_per_kWh", "EUR_per_kWh", "time_start"}


class NotPublishedError(Exception):
    """The API has no prices for this day yet (for example, tomorrow before publication)."""


class BadDataError(ValueError):
    """The API answered, but the data failed a check."""


def build_url(day: date, zone: str) -> str:
    if zone not in config.ZONES:
        raise ValueError(f"Unknown zone {zone!r}. Use one of {config.ZONES}.")
    return config.API_URL.format(year=day.year, month=day.month, day=day.day, zone=zone)


def download_day(day: date, zone: str, session: requests.Session | None = None) -> list[dict]:
    """Fetch the raw JSON for one day and zone. Retries on network errors."""
    session = session or requests.Session()
    url = build_url(day, zone)
    last_error: Exception | None = None

    for attempt in range(1, config.RETRIES + 1):
        try:
            response = session.get(
                url,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": config.USER_AGENT},
            )
            if response.status_code == 404:
                raise NotPublishedError(f"No prices published for {zone} on {day}.")
            response.raise_for_status()
            return response.json()
        except NotPublishedError:
            raise
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < config.RETRIES:
                time.sleep(attempt)  # wait 1s, then 2s, before trying again

    raise ConnectionError(f"Could not fetch {url} after {config.RETRIES} tries: {last_error}")


def parse_day(raw: list[dict], zone: str) -> pd.DataFrame:
    """Check the raw JSON and return one row per hour.

    Columns: zone, hour_utc, sek_per_kwh, eur_per_kwh.
    """
    if not isinstance(raw, list) or not raw:
        raise BadDataError("Expected a non-empty list of price records.")

    missing = REQUIRED_FIELDS - set(raw[0])
    if missing:
        raise BadDataError(f"Price record is missing fields: {sorted(missing)}. Got: {sorted(raw[0])}")

    frame = pd.DataFrame(raw)
    frame["hour_utc"] = pd.to_datetime(frame["time_start"], utc=True).dt.floor("h")

    hourly = (
        frame.groupby("hour_utc", as_index=False)[["SEK_per_kWh", "EUR_per_kWh"]]
        .mean()
        .rename(columns={"SEK_per_kWh": "sek_per_kwh", "EUR_per_kWh": "eur_per_kwh"})
        .sort_values("hour_utc")
        .reset_index(drop=True)
    )

    hours = len(hourly)
    if not config.MIN_HOURS_PER_DAY <= hours <= config.MAX_HOURS_PER_DAY:
        raise BadDataError(f"Expected 23 to 25 hours in a day, got {hours}.")

    if hourly[["sek_per_kwh", "eur_per_kwh"]].isna().any().any():
        raise BadDataError("Found a missing price.")

    low, high = hourly["sek_per_kwh"].min(), hourly["sek_per_kwh"].max()
    if low < config.MIN_PRICE_SEK or high > config.MAX_PRICE_SEK:
        raise BadDataError(f"Price outside sane range: min {low}, max {high} SEK per kWh.")

    hourly.insert(0, "zone", zone)
    return hourly


def fetch_day(day: date, zone: str, session: requests.Session | None = None) -> pd.DataFrame:
    """Download and check one day for one zone."""
    return parse_day(download_day(day, zone, session=session), zone)
