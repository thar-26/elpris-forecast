# elpris-forecast

A daily forecast of Swedish day-ahead electricity prices for the four price zones (SE1 to SE4), scored against what really happened.

**Status: step 1 of 4.** The data pipeline, the baselines and the tests are done. There is no machine learning model yet. That is on purpose: a model only means something once there is a baseline to beat.

## What it does today

1. Downloads hourly prices for every zone from a free public API.
2. Checks every day of data before saving it (right number of hours, no gaps, no absurd prices).
3. Stores the prices in a small SQLite database. Running it twice never creates duplicates.
4. Scores two simple baseline forecasts on the stored history.

## Run it

You need Python 3.10 or newer.

```bash
pip install -e ".[dev]"

pytest                                   # run the tests (no internet needed)
python -m elpris backfill --days 60      # download the last 60 days
python -m elpris backtest                # score the baselines
python -m elpris fetch                   # download today only
```

The database is written to `data/prices.db`. That folder is not stored in git, because the pipeline can rebuild it at any time.

## How it is built

| File | Job |
| --- | --- |
| `src/elpris/config.py` | All settings in one place |
| `src/elpris/fetch.py` | Download one day, retry on network errors, reject bad data |
| `src/elpris/store.py` | Save to and read from SQLite |
| `src/elpris/baseline.py` | The simple forecasts a model has to beat |
| `src/elpris/evaluate.py` | Score forecasts with mean absolute error |
| `src/elpris/cli.py` | The commands above |
| `tests/` | Tests for every file, using made-up prices, so they run offline |

## Choices I made, and why

- **Baselines before models.** "Same hour yesterday" and "same hour last week" cost nothing to run. Any model that cannot beat them is not worth deploying.
- **Mean absolute error, not percentage error.** Electricity prices can be zero or negative, and percentage errors break down there.
- **Fair comparison.** Both baselines are scored on exactly the same hours.
- **Everything in UTC.** Sweden changes clocks twice a year, which gives one 23-hour day and one 25-hour day. Storing UTC avoids both problems.
- **Quarter-hour prices are averaged to hourly.** The source can publish either. Averaging gives the rest of the code one shape to deal with.
- **Bad data stops at the door.** A day that fails a check is reported and skipped. It is never saved.
- **Tests never call the real API.** They would be slow and would fail whenever the API is down.

## Roadmap

- [x] Step 1: fetch, check, store, baselines, tests, automated test run on every push
- [ ] Step 2: a real forecasting model, compared against the baselines on held-out days
- [ ] Step 3: a small web service, Docker, deployment to a cloud platform, daily scheduled run
- [ ] Step 4: daily self-scoring and a public page showing the live track record, including the bad days

## Data

Prices come from the public API at [elprisetjustnu.se](https://www.elprisetjustnu.se/elpris-api). Check their terms before reusing the data.
