"""Command line entry point.

    python -m elpris backfill --days 60    download the last 60 days for all zones
    python -m elpris fetch                 download today (or --date YYYY-MM-DD)
    python -m elpris backtest              score the baselines on everything stored
    python -m elpris compare               test the models against the baseline, day by day
"""

from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

import requests

from . import backtest, config, evaluate, features, fetch, store


def fetch_and_save(connection, session, day: date, zone: str, force: bool = False) -> str:
    """Fetch one day for one zone and save it. Returns a short status word."""
    if not force and store.already_fetched(connection, day, zone):
        return "skipped"
    try:
        hourly = fetch.fetch_day(day, zone, session=session)
    except fetch.NotPublishedError:
        return "not published"
    except (fetch.BadDataError, ConnectionError) as error:
        return f"FAILED: {error}"
    store.save_day(connection, day, hourly)
    return f"saved {len(hourly)} hours"


def run_fetch(days: list[date], db_path, force: bool = False) -> int:
    """Fetch every zone for every day. Returns the number of failures."""
    connection = store.connect(db_path)
    session = requests.Session()
    failures = 0
    for day in days:
        for zone in config.ZONES:
            status = fetch_and_save(connection, session, day, zone, force=force)
            print(f"{day} {zone}: {status}")
            if status.startswith("FAILED"):
                failures += 1
            if status != "skipped":
                time.sleep(config.PAUSE_BETWEEN_REQUESTS_SECONDS)
    connection.close()
    return failures


def run_backtest(db_path) -> int:
    connection = store.connect(db_path)
    prices = store.load_prices(connection)
    connection.close()
    if prices.empty:
        print("No prices stored yet. Run: python -m elpris backfill --days 60")
        return 1
    first, last = prices["hour_utc"].min(), prices["hour_utc"].max()
    print(f"Stored prices: {len(prices)} hourly rows, {first:%Y-%m-%d} to {last:%Y-%m-%d} (UTC)\n")
    results = evaluate.backtest_baselines(prices)
    if results.empty:
        print("Not enough history to score. The weekly baseline needs more than 7 days.")
        return 1
    print(results.to_string(index=False))
    print("\nMAE = average miss in SEK per kWh. Lower is better.")
    return 0


def run_compare(db_path, test_days: int) -> int:
    connection = store.connect(db_path)
    prices = store.load_prices(connection)
    connection.close()
    if prices.empty:
        print("No prices stored yet. Run: python -m elpris backfill --days 60")
        return 1
    try:
        predictions = backtest.walk_forward(features.build_features(prices), test_days=test_days)
    except ValueError as error:
        print(error)
        return 1
    results = evaluate.compare_methods(predictions, reference=backtest.REFERENCE)
    first, last = predictions["local_date"].min(), predictions["local_date"].max()
    print(f"Walk-forward test on {test_days} days, {first} to {last}.")
    print("Each day is forecast using only the days before it.\n")
    print(results.astype(object).fillna("").to_string(index=False))
    print(
        "\ngain_pct = how much lower the error is than same_hour_yesterday."
        "\ngain_low to gain_high = 95% range for the average daily gain in SEK per kWh."
        "\nIf that range includes zero, the win could be luck: 'not proven'."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="elpris", description="Swedish electricity price forecast")
    parser.add_argument("--db", default=str(config.DB_PATH), help="path to the SQLite database")
    commands = parser.add_subparsers(dest="command", required=True)

    backfill = commands.add_parser("backfill", help="download the last N days")
    backfill.add_argument("--days", type=int, default=60)
    backfill.add_argument("--force", action="store_true", help="download again even if already stored")

    one_day = commands.add_parser("fetch", help="download one day (default: today)")
    one_day.add_argument("--date", type=date.fromisoformat, default=None)
    one_day.add_argument("--force", action="store_true")

    commands.add_parser("backtest", help="score the baselines on stored prices")

    compare = commands.add_parser("compare", help="test the models against the baseline")
    compare.add_argument("--test-days", type=int, default=28)

    args = parser.parse_args(argv)

    if args.command == "backfill":
        today = date.today()
        days = [today - timedelta(days=offset) for offset in range(args.days, -1, -1)]
        return 1 if run_fetch(days, args.db, force=args.force) else 0
    if args.command == "fetch":
        return 1 if run_fetch([args.date or date.today()], args.db, force=args.force) else 0
    if args.command == "compare":
        return run_compare(args.db, args.test_days)
    return run_backtest(args.db)


if __name__ == "__main__":
    raise SystemExit(main())
