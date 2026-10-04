"""A small web service that shows the forecasts and the track record.

It keeps no data of its own. It reads the two record files that the daily run
publishes, so the service can be restarted or replaced at any time without losing anything.

    uvicorn elpris.api:app --reload      run it on your own machine
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Callable

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import __version__, config, page, record

DEFAULT_RECORD_URL = "https://raw.githubusercontent.com/thar-26/elpris-forecast/main/record"
CACHE_SECONDS = 600  # ask GitHub at most once every ten minutes

Record = dict  # {"forecasts", "scores", "actuals", "backtest"}: four tables
Loader = Callable[[], Record]

FILES = {
    "forecasts": (record.FORECASTS_FILE, record.FORECAST_COLUMNS),
    "scores": (record.SCORES_FILE, record.SCORE_COLUMNS),
    "actuals": (record.ACTUALS_FILE, record.ACTUAL_COLUMNS),
    "backtest": (record.BACKTEST_FILE, record.BACKTEST_COLUMNS),
}


def load_from_folder(folder: Path | str) -> Record:
    return {
        "forecasts": record.read_forecasts(folder),
        "scores": record.read_scores(folder),
        "actuals": record.read_actuals(folder),
        "backtest": record.read_backtest(folder),
    }


def load_from_url(base_url: str) -> Record:
    """Read the record files over the web. A missing file just means that part does not exist yet."""
    tables = {}
    for name, (filename, columns) in FILES.items():
        response = requests.get(f"{base_url}/{filename}", timeout=config.REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 404:
            tables[name] = pd.DataFrame(columns=columns)
            continue
        response.raise_for_status()
        tables[name] = pd.read_csv(io.StringIO(response.text), dtype={"delivery_date": str, "zone": str})
    return tables


def default_loader() -> Loader:
    """Use a local folder if ELPRIS_RECORD_DIR is set, otherwise the public record on GitHub."""
    folder = os.environ.get("ELPRIS_RECORD_DIR")
    if folder:
        return lambda: load_from_folder(folder)
    url = os.environ.get("ELPRIS_RECORD_URL", DEFAULT_RECORD_URL)
    return lambda: load_from_url(url)


def cached(loader: Loader, seconds: float) -> Loader:
    """Remember the last answer for a while. If a refresh fails, keep serving the old answer."""
    state: dict = {"at": None, "value": None}

    def load():
        now = time.monotonic()
        if state["value"] is None or now - state["at"] > seconds:
            try:
                state["value"], state["at"] = loader(), now
            except Exception:
                if state["value"] is None:
                    raise
        return state["value"]

    return load


def create_app(loader: Loader | None = None, cache_seconds: float = CACHE_SECONDS) -> FastAPI:
    load = cached(loader or default_loader(), cache_seconds)
    app = FastAPI(
        title="elpris-forecast",
        version=__version__,
        description="Daily forecast of Swedish day-ahead electricity prices, with a public track record.",
    )

    def get_record() -> Record:
        try:
            return load()
        except Exception as error:
            raise HTTPException(status_code=503, detail=f"The record could not be loaded: {error}")

    def check_zone(zone: str) -> str:
        zone = zone.upper()
        if zone not in config.ZONES:
            raise HTTPException(status_code=422, detail=f"Unknown zone. Use one of {list(config.ZONES)}.")
        return zone

    @app.get("/health")
    def health() -> dict:
        """Used by the hosting platform to check the service is alive. Touches no data."""
        return {"status": "ok", "version": __version__}

    @app.get("/forecast")
    def get_forecast(
        zone: str = Query(..., description="SE1, SE2, SE3 or SE4"),
        date: str | None = Query(None, description="Delivery date, YYYY-MM-DD. Default: the newest forecast."),
    ) -> dict:
        zone = check_zone(zone)
        forecasts = get_record()["forecasts"]
        rows = forecasts[forecasts["zone"] == zone]
        if rows.empty:
            raise HTTPException(status_code=404, detail=f"No forecasts recorded for {zone} yet.")
        day = date or rows["delivery_date"].max()
        rows = rows[rows["delivery_date"] == day].sort_values("hour_utc")
        if rows.empty:
            raise HTTPException(status_code=404, detail=f"No forecast recorded for {zone} on {day}.")
        return {
            "zone": zone,
            "delivery_date": day,
            "model": rows["model"].iloc[0],
            "made_at_utc": rows["made_at_utc"].iloc[0],
            "unit": "SEK per kWh",
            "hours": [
                {
                    "hour_utc": row.hour_utc,
                    "forecast": float(row.forecast_sek_per_kwh),
                    "baseline": float(row.baseline_sek_per_kwh),
                }
                for row in rows.itertuples(index=False)
            ],
        }

    @app.get("/scores")
    def get_scores(zone: str | None = Query(None, description="Leave empty for all zones")) -> list[dict]:
        scores = get_record()["scores"]
        if zone is not None:
            scores = scores[scores["zone"] == check_zone(zone)]
        scores = scores.sort_values(["delivery_date", "zone"], ascending=[False, True])
        return [
            {
                "delivery_date": row.delivery_date,
                "zone": row.zone,
                "hours": int(row.hours),
                "mae_model": float(row.mae_model),
                "mae_baseline": float(row.mae_baseline),
                "model_won": bool(row.model_won),
            }
            for row in scores.itertuples(index=False)
        ]

    @app.get("/summary")
    def get_summary() -> dict:
        data = get_record()
        forecasts, scores = data["forecasts"], data["scores"]
        return {
            "unit": "SEK per kWh",
            "days_forecast": int(forecasts["delivery_date"].nunique()),
            "days_scored": int(scores["delivery_date"].nunique()),
            "since": scores["delivery_date"].min() if not scores.empty else None,
            "zones": record.summarise(scores),
        }

    @app.get("/", response_class=HTMLResponse)
    def home(zone: str = Query(page.DEFAULT_ZONE, description="The price area to show")) -> str:
        return page.render(get_record(), zone=check_zone(zone))

    return app


app = create_app()
