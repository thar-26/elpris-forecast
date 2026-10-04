from datetime import date

from elpris import fetch, store

DAY = date(2026, 10, 3)


def test_saved_prices_come_back_the_same(raw_day):
    connection = store.connect(":memory:")
    hourly = fetch.parse_day(raw_day(DAY), "SE3")
    assert store.save_day(connection, DAY, hourly) == 24

    loaded = store.load_prices(connection)
    assert len(loaded) == 24
    assert list(loaded["hour_utc"]) == list(hourly["hour_utc"])
    assert list(loaded["sek_per_kwh"].round(5)) == list(hourly["sek_per_kwh"].round(5))


def test_saving_the_same_day_twice_does_not_duplicate(raw_day):
    connection = store.connect(":memory:")
    hourly = fetch.parse_day(raw_day(DAY), "SE3")
    store.save_day(connection, DAY, hourly)
    store.save_day(connection, DAY, hourly)
    assert len(store.load_prices(connection)) == 24


def test_fetch_log_remembers_what_was_fetched(raw_day):
    connection = store.connect(":memory:")
    assert not store.already_fetched(connection, DAY, "SE3")
    store.save_day(connection, DAY, fetch.parse_day(raw_day(DAY), "SE3"))
    assert store.already_fetched(connection, DAY, "SE3")
    assert not store.already_fetched(connection, DAY, "SE4")


def test_load_can_filter_by_zone(raw_day):
    connection = store.connect(":memory:")
    for zone in ("SE3", "SE4"):
        store.save_day(connection, DAY, fetch.parse_day(raw_day(DAY), zone))
    assert len(store.load_prices(connection)) == 48
    assert set(store.load_prices(connection, zone="SE4")["zone"]) == {"SE4"}


def test_database_file_and_folder_are_created(tmp_path):
    db_path = tmp_path / "nested" / "prices.db"
    store.connect(db_path).close()
    assert db_path.exists()
