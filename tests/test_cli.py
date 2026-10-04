from datetime import date, timedelta

from elpris import cli, fetch, store


def test_backfill_then_backtest_runs_end_to_end(tmp_path, monkeypatch, raw_day, capsys):
    """Fake the download, then run the real save, load and scoring code."""
    db_path = tmp_path / "prices.db"
    calls = []

    def fake_fetch_day(day, zone, session=None):
        calls.append((day, zone))
        return fetch.parse_day(raw_day(day), zone)

    monkeypatch.setattr(fetch, "fetch_day", fake_fetch_day)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    days = [date(2026, 9, 1) + timedelta(days=offset) for offset in range(10)]
    assert cli.run_fetch(days, db_path) == 0
    assert len(calls) == 10 * 4

    # running it again downloads nothing
    assert cli.run_fetch(days, db_path) == 0
    assert len(calls) == 10 * 4

    connection = store.connect(db_path)
    assert len(store.load_prices(connection)) == 10 * 4 * 24
    connection.close()

    assert cli.run_backtest(db_path) == 0
    output = capsys.readouterr().out
    assert "same_hour_yesterday" in output and "SE4" in output


def test_a_bad_day_is_reported_and_the_run_continues(tmp_path, monkeypatch, raw_day):
    def flaky_fetch_day(day, zone, session=None):
        if zone == "SE2":
            raise fetch.BadDataError("broken")
        return fetch.parse_day(raw_day(day), zone)

    monkeypatch.setattr(fetch, "fetch_day", flaky_fetch_day)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    failures = cli.run_fetch([date(2026, 9, 1)], tmp_path / "prices.db")
    assert failures == 1
    connection = store.connect(tmp_path / "prices.db")
    assert set(store.load_prices(connection)["zone"]) == {"SE1", "SE3", "SE4"}


def test_backtest_with_no_data_explains_what_to_do(tmp_path, capsys):
    assert cli.run_backtest(tmp_path / "empty.db") == 1
    assert "backfill" in capsys.readouterr().out


def test_compare_runs_end_to_end_on_stored_prices(tmp_path, long_prices, capsys):
    db_path = tmp_path / "prices.db"
    connection = store.connect(db_path)
    for (zone, day), hours in long_prices.assign(eur_per_kwh=0.0).groupby(
        ["zone", long_prices["hour_utc"].dt.date]
    ):
        store.save_day(connection, day, hours[["zone", "hour_utc", "sek_per_kwh", "eur_per_kwh"]])
    connection.close()

    assert cli.run_compare(db_path, test_days=7) == 0
    output = capsys.readouterr().out
    assert "Walk-forward test on 7 days" in output
    assert "ridge" in output and "reference" in output


def test_compare_with_too_little_history_explains_what_to_do(tmp_path, long_prices, capsys):
    db_path = tmp_path / "prices.db"
    connection = store.connect(db_path)
    short = long_prices[long_prices["hour_utc"] < "2026-06-12"].assign(eur_per_kwh=0.0)
    for (zone, day), hours in short.groupby(["zone", short["hour_utc"].dt.date]):
        store.save_day(connection, day, hours[["zone", "hour_utc", "sek_per_kwh", "eur_per_kwh"]])
    connection.close()

    assert cli.run_compare(db_path, test_days=28) == 1
    assert "Download more history" in capsys.readouterr().out


def _fill_database(db_path, prices):
    connection = store.connect(db_path)
    prices = prices.assign(eur_per_kwh=0.0)
    for (zone, day), hours in prices.groupby(["zone", prices["hour_utc"].dt.date]):
        store.save_day(connection, day, hours[["zone", "hour_utc", "sek_per_kwh", "eur_per_kwh"]])
    connection.close()


def test_forecast_then_score_from_the_command_line(tmp_path, long_prices, capsys):
    from elpris import forecast, record

    day = date(2026, 7, 20)
    morning_db, later_db = tmp_path / "morning.db", tmp_path / "later.db"
    record_dir = tmp_path / "record"
    _fill_database(morning_db, long_prices[long_prices["hour_utc"] < forecast.delivery_hours(day)[0]])
    _fill_database(later_db, long_prices)

    assert cli.main(["--db", str(morning_db), "forecast", "--date", "2026-07-20", "--record-dir", str(record_dir)]) == 0
    assert "added 48 hourly rows" in capsys.readouterr().out

    # the same morning: nothing to score, and forecasting again changes nothing
    assert cli.main(["--db", str(morning_db), "score", "--record-dir", str(record_dir)]) == 0
    assert "Nothing new to score" in capsys.readouterr().out
    assert cli.main(["--db", str(morning_db), "forecast", "--date", "2026-07-20", "--record-dir", str(record_dir)]) == 0
    assert "already recorded" in capsys.readouterr().out

    # later, once the real prices are in
    assert cli.main(["--db", str(later_db), "score", "--record-dir", str(record_dir)]) == 0
    assert "Scored 1 day(s)" in capsys.readouterr().out
    assert len(record.read_scores(record_dir)) == 2
    assert (record_dir / "README.md").exists()


def test_forecast_without_history_fails_with_a_message(tmp_path, capsys):
    code = cli.main(["--db", str(tmp_path / "empty.db"), "forecast", "--record-dir", str(tmp_path / "record")])
    assert code == 1
    assert "Could not forecast" in capsys.readouterr().out
