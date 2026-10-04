# elpris-forecast

A daily forecast of Swedish day-ahead electricity prices for the four price zones (SE1 to SE4), scored against what really happened.

**Status: step 3 of 4, in progress.** The pipeline, the baselines and the model are built and tested. On a 180-day test the model beats the baseline in all four zones. A daily automatic run is set up on GitHub, and its results are published in the [live track record](record/README.md). Cloud deployment is not done yet.

## What it does today

1. Downloads hourly prices for every zone from a free public API.
2. Checks every day of data before saving it (right number of hours, no gaps, no absurd prices).
3. Stores the prices in a small SQLite database. Running it twice never creates duplicates.
4. Scores two simple baseline forecasts on the stored history.
5. Tests two models against the baseline by replaying the past one day at a time.
6. Every morning, on its own: downloads new prices, scores the earlier forecasts, forecasts tomorrow, and publishes both.

## Run it

You need Python 3.10 or newer.

```bash
pip install -e ".[dev]"

pytest                                   # run the tests (no internet needed)
python -m elpris backfill --days 730     # download two years (30 to 45 minutes)
python -m elpris backtest                # score the baselines
python -m elpris compare --test-days 180 # test the models against the baseline
python -m elpris fetch                   # download today only

python -m elpris forecast --record-dir local_record   # forecast tomorrow
python -m elpris score --record-dir local_record      # score earlier forecasts
```

The `record/` folder belongs to the daily run on GitHub. When trying the last two commands on your own machine, use `--record-dir local_record` as shown, so your experiments never mix with the public record.

The database is written to `data/prices.db`. That folder is not stored in git, because the pipeline can rebuild it at any time.

## Results so far

Tested on 180 days (8 April to 4 October 2026), with about two years of history. Each day was forecast using only the days before it. Error is the average miss in SEK per kWh.

| Zone | Same hour yesterday | Ridge model | Error reduced by | Days won | Verdict |
| --- | --- | --- | --- | --- | --- |
| SE1 | 0.2482 | 0.2165 | 12.8% | 114 of 180 | beats baseline |
| SE2 | 0.2598 | 0.2297 | 11.6% | 114 of 180 | beats baseline |
| SE3 | 0.3299 | 0.2817 | 14.6% | 121 of 180 | beats baseline |
| SE4 | 0.4226 | 0.3731 | 11.7% | 114 of 180 | beats baseline |

How to read this honestly:

- The model's error is 12% to 15% lower than the baseline, and the lead holds up in every zone. The 95% range for the daily gain stays above zero.
- It is a modest win, not a large one. The model still loses on about one day in three, and it still misses by 0.22 to 0.37 SEK per kWh on average.
- Gradient boosting scored about the same as ridge regression (within 0.01 in every zone). I chose ridge because it is simpler, faster to retrain and easier to explain.
- A plain 50/50 mix of yesterday's price and last week's average was not proven better than the baseline. So the model is doing more than just smoothing.

An earlier test on only 28 days showed gains of 12% to 18%, but could not prove them in three of the four zones. The longer test was needed to settle it.

## The daily run

A scheduled GitHub Actions job (`.github/workflows/daily.yml`) runs every morning at 05:17 UTC, hours before the next day's real prices are published.

1. It restores the price database from the previous run and downloads whatever is new.
2. It scores every earlier forecast whose real prices are now known.
3. It retrains the model on all history and forecasts tomorrow.
4. It commits the forecast and the scores to `record/`.

What keeps the record honest:

- A forecast is written once. Code refuses to overwrite a day that is already recorded, and a test checks this.
- The forecast for a day is identical whether or not that day's real prices are already in the database. A test checks this too.
- The record lives in git, so every change to it has a timestamp and a visible history.
- If the job fails, GitHub shows a red run and sends an email. A missing day stays missing. It is not filled in afterwards.

## How it is built

| File | Job |
| --- | --- |
| `src/elpris/config.py` | All settings in one place |
| `src/elpris/fetch.py` | Download one day, retry on network errors, reject bad data |
| `src/elpris/store.py` | Save to and read from SQLite |
| `src/elpris/baseline.py` | The simple forecasts a model has to beat |
| `src/elpris/features.py` | Turn prices into model inputs, never using the future |
| `src/elpris/backtest.py` | Replay the past day by day, training only on earlier days |
| `src/elpris/evaluate.py` | Score forecasts and say whether a win is proven |
| `src/elpris/forecast.py` | Make the real forecast for one delivery day |
| `src/elpris/record.py` | Keep the public record of forecasts and scores |
| `src/elpris/cli.py` | The commands above |
| `tests/` | Tests for every file, using made-up prices, so they run offline |

## Choices I made, and why

- **Baselines before models.** "Same hour yesterday" and "same hour last week" cost nothing to run. Any model that cannot beat them is not worth deploying.
- **No input is newer than 24 hours before the hour it predicts.** Tomorrow's forecast is made today, so only prices up to the end of today may be used. A test changes all later prices and checks that the inputs stay the same.
- **Walk-forward testing.** Every test day is forecast by a model trained only on earlier days. That copies real use, where tomorrow is always unseen.
- **A win has to be proven.** The comparison gives a 95% range for the daily gain. If the range includes zero, the result is marked "not proven", even when the average looks good.
- **The simplest model that wins.** Ridge regression with eight inputs matched gradient boosting on the 180-day test, so ridge is the one that will be deployed.
- **Mean absolute error, not percentage error.** Electricity prices can be zero or negative, and percentage errors break down there.
- **Everything in UTC.** Sweden changes clocks twice a year, which gives one 23-hour day and one 25-hour day. Storing UTC avoids both problems.
- **Quarter-hour prices are averaged to hourly.** The source can publish either. Averaging gives the rest of the code one shape to deal with.
- **Bad data stops at the door.** A day that fails a check is reported and skipped. It is never saved.
- **Live inputs are built by the same code as test inputs.** One function builds the model inputs for both. A test checks that the numbers for a future hour are the same before and after its price arrives.
- **Tests never call the real API.** They would be slow and would fail whenever the API is down.

## What the model does not know yet

It only sees past prices. It knows nothing about wind, temperature or power cable outages, which are what really move the price from one day to the next. Adding a weather forecast is the most likely way to make a real improvement.

## Roadmap

- [x] Step 1: fetch, check, store, baselines, tests, automated test run on every push
- [x] Step 2: forecasting model, tested day by day against the baselines on 180 days
- [ ] Step 3: daily scheduled run with a public track record (set up), then a web service, Docker and a cloud deployment
- [ ] Step 4: 30 days of live results, and weather forecasts as model inputs

## Data

Prices come from the public API at [elprisetjustnu.se](https://www.elprisetjustnu.se/elpris-api). Check their terms before reusing the data.
