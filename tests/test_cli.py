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
