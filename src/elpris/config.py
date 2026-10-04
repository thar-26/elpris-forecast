"""Settings for the whole project, kept in one place."""

from pathlib import Path

# The four Swedish electricity price zones, north to south.
ZONES = ("SE1", "SE2", "SE3", "SE4")

# Free public API for Swedish day-ahead prices. One request = one day in one zone.
API_URL = "https://www.elprisetjustnu.se/api/v1/prices/{year}/{month:02d}-{day:02d}_{zone}.json"

# Where the prices are stored on disk.
DB_PATH = Path("data/prices.db")

# Network behaviour.
REQUEST_TIMEOUT_SECONDS = 20
RETRIES = 3
PAUSE_BETWEEN_REQUESTS_SECONDS = 0.5
USER_AGENT = "elpris-forecast (student project)"

# Sanity limits for one hourly price, in SEK per kWh.
# Prices can go below zero, so the lower limit is negative on purpose.
MIN_PRICE_SEK = -10.0
MAX_PRICE_SEK = 100.0

# A normal day has 24 hours. The two clock-change days have 23 and 25.
MIN_HOURS_PER_DAY = 23
MAX_HOURS_PER_DAY = 25
