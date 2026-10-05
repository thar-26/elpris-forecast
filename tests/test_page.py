from datetime import date, datetime, timezone

import pandas as pd
import pytest

from elpris import api, forecast, page, record

DAY = date(2026, 7, 20)
MADE_AT = datetime(2026, 7, 19, 5, 17, tzinfo=timezone.utc)
MORNING_BEFORE = datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def only_forecast(tmp_path, long_prices):
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    record.add_forecasts(tmp_path, forecast.forecast_day(known, DAY), model="ridge", made_at=MADE_AT)
    return api.load_from_folder(tmp_path)


@pytest.fixture
def scored(tmp_path, long_prices):
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    record.add_forecasts(tmp_path, forecast.forecast_day(known, DAY), model="ridge", made_at=MADE_AT)
    record.score_pending(tmp_path, long_prices)
    return api.load_from_folder(tmp_path)


def test_first_day_page_explains_what_is_still_missing(only_forecast):
    text = page.render(only_forecast, zone="SE3", now=MORNING_BEFORE)
    assert "Tomorrow, Monday 20 July: Stockholm (SE3)" in text
    assert "Forecast made 19 July at 07:17" in text          # shown in Swedish time
    assert "Nothing to check yet for Stockholm" in text
    assert "No days have been checked yet" in text
    assert "Tested on" not in text                           # no backtest file, so no backtest section


def test_headline_facts_match_the_forecast(only_forecast):
    rows = only_forecast["forecasts"]
    rows = rows[rows["zone"] == "SE3"]
    cheapest = rows["forecast_sek_per_kwh"].min() * 100
    text = page.render(only_forecast, zone="SE3", now=MORNING_BEFORE)
    assert "Cheapest hour" in text and "Most expensive hour" in text
    assert f"<dd>{cheapest:.0f} " in text or f"<dd>{cheapest:.1f} " in text


def test_scored_day_shows_the_real_price_next_to_the_forecast(scored):
    text = page.render(scored, zone="SE3", now=MORNING_BEFORE)
    assert "Real price" in text and "Simple guess" in text
    assert "On Monday 20 July in Stockholm, the forecast missed the real price by" in text
    assert "1 day checked since 20 July" in text
    assert "Too early to say" in text                        # one day proves nothing


def test_an_area_without_data_gets_a_plain_message(scored):
    text = page.render(scored, zone="SE1", now=MORNING_BEFORE)   # the test data has only SE3 and SE4
    assert "No forecast has been made for this area yet" in text


def test_backtest_section_reports_the_result_in_words(scored):
    scored["backtest"] = pd.DataFrame(
        [
            {"zone": z, "method": m, "mae_sek_per_kwh": mae, "gain_pct": gain, "days_won": 110, "days": 180,
             "gain_low": 0.01, "gain_high": 0.05, "verdict": verdict, "first_day": "2026-04-08", "last_day": "2026-10-04"}
            for z in ("SE3", "SE4")
            for m, mae, gain, verdict in (
                ("same_hour_yesterday", 0.33, 0.0, "reference"),
                ("ridge", 0.28, 14.6 if z == "SE3" else 11.7, "beats baseline"),
            )
        ]
    )
    text = page.render(scored, zone="SE3", now=MORNING_BEFORE)
    assert "Tested on 180 past days first" in text
    assert "8 April to 4 October 2026" in text
    assert "12% to 15% smaller" in text


def test_real_prices_are_recorded_when_a_day_is_scored(tmp_path, long_prices):
    known = long_prices[long_prices["hour_utc"] < forecast.delivery_hours(DAY)[0]]
    record.add_forecasts(tmp_path, forecast.forecast_day(known, DAY), model="ridge", made_at=MADE_AT)
    assert record.read_actuals(tmp_path).empty
    record.score_pending(tmp_path, long_prices)
    actuals = record.read_actuals(tmp_path)
    assert len(actuals) == 48 and set(actuals["zone"]) == {"SE3", "SE4"}
    record.score_pending(tmp_path, long_prices)
    assert len(record.read_actuals(tmp_path)) == 48          # scoring again adds nothing


def test_saved_site_has_one_file_per_area_and_links_between_them(tmp_path, scored):
    written = page.build_site(scored, tmp_path / "site", now=MORNING_BEFORE)
    names = sorted(p.name for p in written)
    assert names == ["index.html", "se1.html", "se2.html", "se3.html", "se4.html"]
    assert (tmp_path / "site" / ".nojekyll").exists()

    home = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert home == (tmp_path / "site" / "se3.html").read_text(encoding="utf-8")   # Stockholm is the front page
    assert 'href="se4.html"' in home
    assert "/?zone=" not in home and 'href="/summary"' not in home               # nothing points at the live service
    assert "Forecast for Monday 20 July: Stockholm (SE3)" in home                # a date, not the word "tomorrow"
    assert "Page updated 19 July 2026 at 10:00 Swedish time" in home
    assert "Malmö (SE4)" in (tmp_path / "site" / "se4.html").read_text(encoding="utf-8")
