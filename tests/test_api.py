from datetime import date, datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from elpris import api, forecast, record

DAY = date(2026, 7, 20)
MADE_AT = datetime(2026, 7, 19, 5, 17, tzinfo=timezone.utc)


@pytest.fixture
def record_dir(tmp_path, long_prices):
    """A record with one day forecast and scored, for SE3 and SE4."""
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    record.add_forecasts(tmp_path, forecast.forecast_day(known, DAY), model="ridge", made_at=MADE_AT)
    record.score_pending(tmp_path, long_prices)
    return tmp_path


@pytest.fixture
def client(record_dir):
    return TestClient(api.create_app(loader=lambda: api.load_from_folder(record_dir), cache_seconds=0))


@pytest.fixture
def empty_client(tmp_path):
    return TestClient(api.create_app(loader=lambda: api.load_from_folder(tmp_path), cache_seconds=0))


def test_health_answers_without_touching_data():
    def broken():
        raise RuntimeError("no data")

    response = TestClient(api.create_app(loader=broken)).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_forecast_returns_the_newest_day_by_default(client):
    body = client.get("/forecast", params={"zone": "SE3"}).json()
    assert body["zone"] == "SE3"
    assert body["delivery_date"] == "2026-07-20"
    assert body["model"] == "ridge"
    assert body["made_at_utc"] == "2026-07-19T05:17:00Z"
    assert len(body["hours"]) == 24
    assert set(body["hours"][0]) == {"hour_utc", "forecast", "baseline"}


def test_zone_is_not_case_sensitive(client):
    assert client.get("/forecast", params={"zone": "se4"}).json()["zone"] == "SE4"


def test_unknown_zone_is_rejected(client):
    response = client.get("/forecast", params={"zone": "NO1"})
    assert response.status_code == 422
    assert "SE1" in response.json()["detail"]


def test_a_day_with_no_forecast_gives_404(client):
    response = client.get("/forecast", params={"zone": "SE3", "date": "2020-01-01"})
    assert response.status_code == 404


def test_scores_can_be_filtered_by_zone(client):
    assert len(client.get("/scores").json()) == 2
    only = client.get("/scores", params={"zone": "SE3"}).json()
    assert len(only) == 1
    assert only[0]["zone"] == "SE3" and only[0]["hours"] == 24
    assert isinstance(only[0]["model_won"], bool)


def test_summary_gives_totals_per_zone(client):
    body = client.get("/summary").json()
    assert body["days_forecast"] == 1 and body["days_scored"] == 1
    assert body["since"] == "2026-07-20"
    zones = {row["zone"]: row for row in body["zones"]}
    assert set(zones) == {"SE3", "SE4"}
    assert zones["SE3"]["verdict"] == "not proven"  # one day proves nothing


def test_home_page_shows_the_forecast_the_check_and_the_score(client):
    response = client.get("/")
    assert response.status_code == 200
    text = response.text
    assert "Stockholm (SE3)" in text            # SE3 is shown by default
    assert "Monday 20 July" in text
    assert "How close was the last forecast?" in text
    assert "The score so far" in text
    assert text.count("<svg") >= 2              # the forecast, and the forecast against reality
    assert 'class="bars"' in text               # the score, as bars
    assert 'src="http' not in text              # nothing is loaded from other sites


def test_home_page_can_show_another_price_area(client):
    text = client.get("/", params={"zone": "se4"}).text
    assert "Malmö (SE4)" in text
    assert client.get("/", params={"zone": "XX"}).status_code == 422


def test_everything_works_before_any_forecast_exists(empty_client):
    assert empty_client.get("/").status_code == 200
    assert "No forecast has been made for this area yet" in empty_client.get("/").text
    assert empty_client.get("/summary").json()["zones"] == []
    assert empty_client.get("/scores").json() == []
    assert empty_client.get("/forecast", params={"zone": "SE3"}).status_code == 404


def test_a_failed_refresh_keeps_serving_the_last_good_data(record_dir):
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] > 1:
            raise RuntimeError("GitHub is down")
        return api.load_from_folder(record_dir)

    client = TestClient(api.create_app(loader=flaky, cache_seconds=0))
    assert client.get("/summary").json()["days_scored"] == 1
    assert client.get("/summary").json()["days_scored"] == 1  # second call fails inside, old data is served
    assert calls["count"] == 2


def test_no_data_at_all_gives_a_clear_503():
    def broken():
        raise RuntimeError("GitHub is down")

    response = TestClient(api.create_app(loader=broken, cache_seconds=0)).get("/summary")
    assert response.status_code == 503
    assert "could not be loaded" in response.json()["detail"]


def test_record_is_fetched_only_once_within_the_cache_time(record_dir):
    calls = {"count": 0}

    def counting():
        calls["count"] += 1
        return api.load_from_folder(record_dir)

    client = TestClient(api.create_app(loader=counting, cache_seconds=600))
    for _ in range(5):
        client.get("/summary")
    assert calls["count"] == 1
