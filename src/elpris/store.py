"""Save prices to a small SQLite database and read them back.

Saving the same hour twice replaces the old row, so re-running a fetch is safe.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from . import config

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    zone        TEXT NOT NULL,
    hour_utc    TEXT NOT NULL,
    sek_per_kwh REAL NOT NULL,
    eur_per_kwh REAL NOT NULL,
    PRIMARY KEY (zone, hour_utc)
);
CREATE TABLE IF NOT EXISTS fetch_log (
    zone       TEXT NOT NULL,
    day        TEXT NOT NULL,
    hours      INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (zone, day)
);
"""


def connect(db_path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    """Open the database, creating the folder and tables if needed."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA)
    return connection


def save_day(connection: sqlite3.Connection, day: date, hourly: pd.DataFrame) -> int:
    """Save one day of hourly prices for one zone. Returns the number of rows saved."""
    rows = [
        (row.zone, row.hour_utc.strftime(TIME_FORMAT), float(row.sek_per_kwh), float(row.eur_per_kwh))
        for row in hourly.itertuples(index=False)
    ]
    zone = hourly["zone"].iloc[0]
    now = datetime.now(timezone.utc).strftime(TIME_FORMAT)
    with connection:
        connection.executemany("INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?)", rows)
        connection.execute(
            "INSERT OR REPLACE INTO fetch_log VALUES (?, ?, ?, ?)",
            (zone, day.isoformat(), len(rows), now),
        )
    return len(rows)


def already_fetched(connection: sqlite3.Connection, day: date, zone: str) -> bool:
    found = connection.execute(
        "SELECT 1 FROM fetch_log WHERE zone = ? AND day = ?", (zone, day.isoformat())
    ).fetchone()
    return found is not None


def load_prices(connection: sqlite3.Connection, zone: str | None = None) -> pd.DataFrame:
    """Read stored prices, oldest first. Columns: zone, hour_utc, sek_per_kwh, eur_per_kwh."""
    query = "SELECT zone, hour_utc, sek_per_kwh, eur_per_kwh FROM prices"
    params: tuple = ()
    if zone is not None:
        query += " WHERE zone = ?"
        params = (zone,)
    query += " ORDER BY zone, hour_utc"
    frame = pd.read_sql_query(query, connection, params=params)
    frame["hour_utc"] = pd.to_datetime(frame["hour_utc"], utc=True)
    return frame
