from datetime import date

import pytest
import requests

from elpris import config, fetch

DAY = date(2026, 10, 3)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Stands in for requests.Session and returns the responses it was given, in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_build_url_uses_zero_padded_date():
    url = fetch.build_url(date(2026, 3, 7), "SE3")
    assert url.endswith("/2026/03-07_SE3.json")


def test_build_url_rejects_unknown_zone():
    with pytest.raises(ValueError):
        fetch.build_url(DAY, "NO1")


def test_quarter_hour_prices_become_24_hourly_averages(raw_day):
    hourly = fetch.parse_day(raw_day(DAY, step_minutes=15), "SE3")
    assert len(hourly) == 24
    assert list(hourly.columns) == ["zone", "hour_utc", "sek_per_kwh", "eur_per_kwh"]
    # local midnight in Stockholm summer time is 22:00 UTC the day before
    assert str(hourly["hour_utc"].iloc[0]) == "2026-10-02 22:00:00+00:00"
    assert hourly["sek_per_kwh"].iloc[0] == pytest.approx(0.50)
    assert hourly["sek_per_kwh"].iloc[-1] == pytest.approx(0.73)


def test_hourly_prices_are_kept_as_they_are(raw_day):
    hourly = fetch.parse_day(raw_day(DAY, step_minutes=60), "SE1")
    assert len(hourly) == 24
    assert set(hourly["zone"]) == {"SE1"}


def test_missing_field_is_rejected(raw_day):
    raw = raw_day(DAY)
    for record in raw:
        del record["SEK_per_kWh"]
    with pytest.raises(fetch.BadDataError, match="missing fields"):
        fetch.parse_day(raw, "SE3")


def test_half_a_day_is_rejected(raw_day):
    with pytest.raises(fetch.BadDataError, match="23 to 25 hours"):
        fetch.parse_day(raw_day(DAY)[:48], "SE3")


def test_empty_answer_is_rejected():
    with pytest.raises(fetch.BadDataError):
        fetch.parse_day([], "SE3")


def test_absurd_price_is_rejected(raw_day):
    raw = raw_day(DAY, step_minutes=60)
    raw[5]["SEK_per_kWh"] = 5000.0
    with pytest.raises(fetch.BadDataError, match="sane range"):
        fetch.parse_day(raw, "SE3")


def test_negative_prices_are_allowed(raw_day):
    raw = raw_day(DAY, step_minutes=60)
    raw[3]["SEK_per_kWh"] = -0.05
    hourly = fetch.parse_day(raw, "SE3")
    assert hourly["sek_per_kwh"].min() == pytest.approx(-0.05)


def test_404_means_not_published_and_is_not_retried():
    session = FakeSession([FakeResponse(status_code=404)])
    with pytest.raises(fetch.NotPublishedError):
        fetch.download_day(DAY, "SE3", session=session)
    assert len(session.urls) == 1


def test_network_error_is_retried_then_succeeds(raw_day, monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)
    session = FakeSession([requests.ConnectionError("down"), FakeResponse(payload=raw_day(DAY))])
    hourly = fetch.fetch_day(DAY, "SE3", session=session)
    assert len(hourly) == 24
    assert len(session.urls) == 2


def test_gives_up_after_all_retries(monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)
    session = FakeSession([requests.ConnectionError("down")] * config.RETRIES)
    with pytest.raises(ConnectionError, match="after 3 tries"):
        fetch.download_day(DAY, "SE3", session=session)
