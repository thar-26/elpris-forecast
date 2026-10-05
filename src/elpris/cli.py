"""Command line entry point.

    python -m elpris backfill --days 60    download the last 60 days for all zones
    python -m elpris fetch                 download today (or --date YYYY-MM-DD)
    python -m elpris backtest              score the baselines on everything stored
    python -m elpris compare               test the models against the baseline, day by day
    python -m elpris forecast              forecast tomorrow and add it to the record
    python -m elpris score                 score recorded forecasts whose real prices are in
    python -m elpris site                  save the web page as plain files, ready to publish
"""

from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from . import backtest, config, evaluate, features, fetch, forecast, page, record, store

RECORD_DIR = "record"


def now_in_sweden() -> datetime:
    return datetime.now(ZoneInfo(features.LOCAL_TIMEZONE))


def today_in_sweden() -> date:
    return now_in_sweden().date()


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


def run_compare(db_path, test_days: int, save_dir=None) -> int:
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
    if save_dir:
        path = record.save_backtest(save_dir, results, first, last)
        print(f"\nSaved to {path}")
    print(
        "\ngain_pct = how much lower the error is than same_hour_yesterday."
        "\ngain_low to gain_high = 95% range for the average daily gain in SEK per kWh."
        "\nIf that range includes zero, the win could be luck: 'not proven'."
    )
    return 0


def run_forecast(db_path, record_dir, day: date, allow_late: bool = False) -> int:
    if not allow_late and forecast.too_late(day, now_in_sweden()):
        if str(day) in set(record.read_forecasts(record_dir)["delivery_date"]):
            print(f"Forecast for {day} is already recorded. Nothing changed.")
        else:
            print(
                f"Too late to forecast {day}. Its real prices may already be public "
                f"(they come out around 13:00 Swedish time the day before), so nothing was recorded. "
                f"For a local test, add --allow-late."
            )
        return 0
    connection = store.connect(db_path)
    prices = store.load_prices(connection)
    connection.close()
    try:
        forecasts = forecast.forecast_day(prices, day)
    except ValueError as error:
        print(f"Could not forecast {day}: {error}")
        return 1
    added = record.add_forecasts(record_dir, forecasts, model=forecast.MODEL_NAME)
    record.write_summary(record_dir)
    if added:
        print(f"Forecast for {day}: added {added} hourly rows to {record_dir}/{record.FORECASTS_FILE}")
    else:
        print(f"Forecast for {day} is already recorded. Nothing changed.")
    return 0


def run_score(db_path, record_dir) -> int:
    connection = store.connect(db_path)
    prices = store.load_prices(connection)
    connection.close()
    new = record.score_pending(record_dir, prices)
    record.write_summary(record_dir)
    if new.empty:
        print("Nothing new to score yet.")
    else:
        print(new.to_string(index=False))
        print(f"\nScored {new['delivery_date'].nunique()} day(s). Summary: {record_dir}/{record.SUMMARY_FILE}")
    return 0


def run_site(record_dir, out_dir) -> int:
    data = {
        "forecasts": record.read_forecasts(record_dir),
        "scores": record.read_scores(record_dir),
        "actuals": record.read_actuals(record_dir),
        "backtest": record.read_backtest(record_dir),
    }
    written = page.build_site(data, out_dir)
    print(f"Saved {len(written)} pages to {out_dir}. Open {out_dir}/index.html in a browser to look at it.")
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
    compare.add_argument("--save", metavar="FOLDER", default=None, help="also save the result as backtest.csv in this folder")

    make_forecast = commands.add_parser("forecast", help="forecast one day (default: tomorrow)")
    make_forecast.add_argument("--date", type=date.fromisoformat, default=None)
    make_forecast.add_argument("--record-dir", default=RECORD_DIR)
    make_forecast.add_argument(
        "--allow-late", action="store_true", help="record it even after the real prices may be public (local tests only)"
    )

    score = commands.add_parser("score", help="score recorded forecasts against real prices")
    score.add_argument("--record-dir", default=RECORD_DIR)

    site = commands.add_parser("site", help="save the web page as plain files")
    site.add_argument("--record-dir", default=RECORD_DIR)
    site.add_argument("--out", default="site")

    args = parser.parse_args(argv)

    if args.command == "backfill":
        today = today_in_sweden()
        days = [today - timedelta(days=offset) for offset in range(args.days, -1, -1)]
        return 1 if run_fetch(days, args.db, force=args.force) else 0
    if args.command == "fetch":
        return 1 if run_fetch([args.date or today_in_sweden()], args.db, force=args.force) else 0
    if args.command == "forecast":
        day = args.date or today_in_sweden() + timedelta(days=1)
        return run_forecast(args.db, args.record_dir, day, allow_late=args.allow_late)
    if args.command == "score":
        return run_score(args.db, args.record_dir)
    if args.command == "site":
        return run_site(args.record_dir, args.out)
    if args.command == "compare":
        return run_compare(args.db, args.test_days, save_dir=args.save)
    return run_backtest(args.db)


if __name__ == "__main__":
    raise SystemExit(main())
