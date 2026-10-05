"""The public track record: what was forecast, and how wrong it was.

Plain CSV files, kept in git so every change is visible:

    record/forecasts.csv   one row per zone and hour, written when the forecast is made
    record/scores.csv      one row per zone and day, written once the real prices are known
    record/actuals.csv     the real prices for every scored hour, so anyone can redo the scoring
    record/backtest.csv    the test on past days that was run before going live (optional)
    record/plan.csv        what picking the cheapest hours with the forecast would have cost (optional)

A forecast is written once and never changed. Scoring a day twice changes nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .evaluate import gain_range, verdict
from .store import TIME_FORMAT

FORECAST_COLUMNS = [
    "delivery_date",
    "zone",
    "hour_utc",
    "forecast_sek_per_kwh",
    "baseline_sek_per_kwh",
    "model",
    "made_at_utc",
]
SCORE_COLUMNS = ["delivery_date", "zone", "hours", "mae_model", "mae_baseline", "model_won"]
ACTUAL_COLUMNS = ["zone", "hour_utc", "sek_per_kwh"]
BACKTEST_COLUMNS = [
    "zone", "method", "mae_sek_per_kwh", "gain_pct", "days_won", "days",
    "gain_low", "gain_high", "verdict", "first_day", "last_day",
]

PLAN_COLUMNS = [
    "zone", "plan", "paid_sek_per_kwh", "saving_pct", "days_won", "days_lost", "days",
    "gain_low", "gain_high", "verdict", "hours", "first_day", "last_day",
]

FORECASTS_FILE = "forecasts.csv"
SCORES_FILE = "scores.csv"
ACTUALS_FILE = "actuals.csv"
BACKTEST_FILE = "backtest.csv"
PLAN_FILE = "plan.csv"
SUMMARY_FILE = "README.md"


def _read(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    return pd.read_csv(path, dtype={"delivery_date": str, "zone": str})


def read_forecasts(record_dir: Path | str) -> pd.DataFrame:
    return _read(Path(record_dir) / FORECASTS_FILE, FORECAST_COLUMNS)


def read_scores(record_dir: Path | str) -> pd.DataFrame:
    return _read(Path(record_dir) / SCORES_FILE, SCORE_COLUMNS)


def read_actuals(record_dir: Path | str) -> pd.DataFrame:
    path = Path(record_dir) / ACTUALS_FILE
    return pd.read_csv(path, dtype={"zone": str}) if path.exists() else pd.DataFrame(columns=ACTUAL_COLUMNS)


def read_backtest(record_dir: Path | str) -> pd.DataFrame:
    path = Path(record_dir) / BACKTEST_FILE
    return pd.read_csv(path, dtype={"zone": str}) if path.exists() else pd.DataFrame(columns=BACKTEST_COLUMNS)


def save_backtest(record_dir: Path | str, results: pd.DataFrame, first_day, last_day) -> Path:
    """Save the result of `compare`, with the test window, so the web page can show it."""
    record_dir = Path(record_dir)
    record_dir.mkdir(parents=True, exist_ok=True)
    out = results.assign(first_day=str(first_day), last_day=str(last_day))[BACKTEST_COLUMNS]
    path = record_dir / BACKTEST_FILE
    out.to_csv(path, index=False)
    return path


def read_plan(record_dir: Path | str) -> pd.DataFrame:
    path = Path(record_dir) / PLAN_FILE
    if not path.exists():
        return pd.DataFrame(columns=PLAN_COLUMNS)
    return pd.read_csv(path, dtype={"zone": str}, keep_default_na=False, na_values=[""]).fillna({"verdict": ""})


def save_plan(record_dir: Path | str, results: pd.DataFrame, hours: int, first_day, last_day) -> Path:
    """Save the result of `plan`, with the number of hours and the test window, so the web page can show it."""
    record_dir = Path(record_dir)
    record_dir.mkdir(parents=True, exist_ok=True)
    out = results.assign(hours=hours, first_day=str(first_day), last_day=str(last_day))[PLAN_COLUMNS]
    path = record_dir / PLAN_FILE
    out.to_csv(path, index=False)
    return path


def add_forecasts(record_dir: Path | str, forecasts: pd.DataFrame, model: str, made_at: datetime | None = None) -> int:
    """Append new forecasts. A day and zone that is already recorded is left untouched.

    Returns the number of rows added.
    """
    record_dir = Path(record_dir)
    record_dir.mkdir(parents=True, exist_ok=True)
    existing = read_forecasts(record_dir)
    already = set(zip(existing["delivery_date"], existing["zone"]))

    new = forecasts[[(d, z) not in already for d, z in zip(forecasts["delivery_date"], forecasts["zone"])]].copy()
    if new.empty:
        return 0

    made_at = made_at or datetime.now(timezone.utc)
    new["hour_utc"] = pd.to_datetime(new["hour_utc"], utc=True).dt.strftime(TIME_FORMAT)
    new["model"] = model
    new["made_at_utc"] = made_at.strftime(TIME_FORMAT)

    combined = pd.concat([existing, new[FORECAST_COLUMNS]], ignore_index=True)
    combined.to_csv(record_dir / FORECASTS_FILE, index=False)
    return len(new)


def score_pending(record_dir: Path | str, prices: pd.DataFrame) -> pd.DataFrame:
    """Score every recorded day whose real prices are now known and that has no score yet.

    Returns the new score rows (also appended to scores.csv).
    """
    record_dir = Path(record_dir)
    forecasts = read_forecasts(record_dir)
    scores = read_scores(record_dir)
    if forecasts.empty:
        return pd.DataFrame(columns=SCORE_COLUMNS)

    done = set(zip(scores["delivery_date"], scores["zone"]))
    forecasts["hour_utc"] = pd.to_datetime(forecasts["hour_utc"], utc=True)
    merged = forecasts.merge(
        prices[["zone", "hour_utc", "sek_per_kwh"]], on=["zone", "hour_utc"], how="left"
    )

    rows, real_prices = [], []
    for (day, zone), group in merged.groupby(["delivery_date", "zone"]):
        if (day, zone) in done or group["sek_per_kwh"].isna().any():
            continue  # already scored, or the real prices are not all in yet
        real_prices.append(group[["zone", "hour_utc", "sek_per_kwh"]])
        mae_model = (group["sek_per_kwh"] - group["forecast_sek_per_kwh"]).abs().mean()
        mae_baseline = (group["sek_per_kwh"] - group["baseline_sek_per_kwh"]).abs().mean()
        rows.append(
            {
                "delivery_date": day,
                "zone": zone,
                "hours": len(group),
                "mae_model": round(float(mae_model), 4),
                "mae_baseline": round(float(mae_baseline), 4),
                "model_won": int(mae_model < mae_baseline),
            }
        )

    new = pd.DataFrame(rows, columns=SCORE_COLUMNS)
    if not new.empty:
        combined = pd.concat([scores, new], ignore_index=True).sort_values(["delivery_date", "zone"])
        combined.to_csv(record_dir / SCORES_FILE, index=False)

        fresh = pd.concat(real_prices, ignore_index=True)
        fresh["hour_utc"] = fresh["hour_utc"].dt.strftime(TIME_FORMAT)
        fresh["sek_per_kwh"] = fresh["sek_per_kwh"].round(5)
        actuals = pd.concat([read_actuals(record_dir), fresh], ignore_index=True)
        actuals = actuals.drop_duplicates(["zone", "hour_utc"]).sort_values(["zone", "hour_utc"])
        actuals.to_csv(record_dir / ACTUALS_FILE, index=False)
    return new


def summarise(scores: pd.DataFrame) -> list[dict]:
    """Totals per zone: days scored, both errors, how much lower the model's is, and whether that is proven."""
    rows = []
    for zone, group in scores.groupby("zone"):
        model, baseline = float(group["mae_model"].mean()), float(group["mae_baseline"].mean())
        if len(group) >= 2:
            proven = verdict(*gain_range(group["mae_baseline"] - group["mae_model"]))
        else:
            proven = "not proven"  # one day can never prove anything
        rows.append(
            {
                "zone": zone,
                "days_scored": int(len(group)),
                "mae_model": round(model, 4),
                "mae_baseline": round(baseline, 4),
                "error_reduced_pct": round(100 * (baseline - model) / baseline, 1) if baseline else 0.0,
                "days_model_won": int(group["model_won"].sum()),
                "verdict": proven,
            }
        )
    return rows


UPDATED_LINE = "Updated automatically. Last update:"


def _without_update_time(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith(UPDATED_LINE))


def write_summary(record_dir: Path | str, now: datetime | None = None) -> Path:
    """Write record/README.md, a page anyone can read on GitHub.

    If nothing but the update time would change, the file is left alone,
    so a run with no news does not create an empty commit.
    """
    record_dir = Path(record_dir)
    record_dir.mkdir(parents=True, exist_ok=True)
    scores = read_scores(record_dir)
    forecasts = read_forecasts(record_dir)
    now = now or datetime.now(timezone.utc)

    lines = [
        "# Live track record",
        "",
        f"{UPDATED_LINE} {now:%Y-%m-%d %H:%M} UTC.",
        "",
        "Every forecast for a day uses only prices up to the end of the day before it.",
        "A forecast is written once and never edited. `made_at_utc` in `forecasts.csv` shows when.",
        "Miss = average error in SEK per kWh. Lower is better.",
        "The baseline is the price at the same hour the day before.",
        "",
    ]

    if scores.empty:
        waiting = forecasts["delivery_date"].nunique()
        lines += [f"No days scored yet. Forecasts waiting for real prices: {waiting} day(s).", ""]
    else:
        lines += [
            f"## Totals since {scores['delivery_date'].min()}",
            "",
            "| Zone | Days scored | Model miss | Baseline miss | Error reduced by | Days model won | Proven? |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in summarise(scores):
            lines.append(
                f"| {row['zone']} | {row['days_scored']} | {row['mae_model']:.4f} | {row['mae_baseline']:.4f} "
                f"| {row['error_reduced_pct']:.1f}% | {row['days_model_won']} of {row['days_scored']} | {row['verdict']} |"
            )
        lines += [
            "",
            '"Not proven" means the lead could still be luck. It takes weeks of days to settle.',
            "",
            "## Last 14 days",
            "",
            "| Date | Zone | Model miss | Baseline miss | Winner |",
            "| --- | --- | --- | --- | --- |",
        ]
        recent_days = sorted(scores["delivery_date"].unique())[-14:]
        recent = scores[scores["delivery_date"].isin(recent_days)].sort_values(
            ["delivery_date", "zone"], ascending=[False, True]
        )
        for row in recent.itertuples(index=False):
            winner = "model" if row.model_won else "baseline"
            lines.append(
                f"| {row.delivery_date} | {row.zone} | {row.mae_model:.4f} | {row.mae_baseline:.4f} | {winner} |"
            )
        lines.append("")

    path = record_dir / SUMMARY_FILE
    text = "\n".join(lines)
    if path.exists() and _without_update_time(path.read_text(encoding="utf-8")) == _without_update_time(text):
        return path
    path.write_text(text, encoding="utf-8")
    return path
