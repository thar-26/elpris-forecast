import pandas as pd
import pytest

from elpris.baseline import naive_forecast


def test_forecast_for_an_hour_is_the_price_24_hours_earlier(hourly_prices):
    forecast = naive_forecast(hourly_prices, lag_hours=24)
    merged = hourly_prices.merge(forecast, on=["zone", "hour_utc"])
    # prices rise by 0.01 per hour, so the price 24 hours earlier is 0.24 lower
    assert len(merged) == 240 - 24
    assert (merged["sek_per_kwh"] - merged["forecast_sek_per_kwh"]).round(2).eq(0.24).all()


def test_forecast_never_uses_the_future(hourly_prices):
    forecast = naive_forecast(hourly_prices, lag_hours=24)
    first_forecast_hour = forecast["hour_utc"].min()
    assert first_forecast_hour == hourly_prices["hour_utc"].min() + pd.Timedelta(hours=24)


def test_zones_are_kept_separate(hourly_prices):
    other = hourly_prices.assign(zone="SE4", sek_per_kwh=9.0)
    forecast = naive_forecast(pd.concat([hourly_prices, other]), lag_hours=24)
    assert set(forecast.loc[forecast["zone"] == "SE4", "forecast_sek_per_kwh"]) == {9.0}


def test_lag_must_be_positive(hourly_prices):
    with pytest.raises(ValueError):
        naive_forecast(hourly_prices, lag_hours=0)
