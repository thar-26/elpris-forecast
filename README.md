# elpris-forecast

A daily forecast of Swedish day-ahead electricity prices for the four price zones (SE1 to SE4), scored against what really happened.

**Live page: https://thar-26.github.io/elpris-forecast/**

**Status: step 3 of 4 done.** The pipeline, the baselines and the model are built and tested. On a 180-day test the model beats the baseline in all four zones. A daily automatic run publishes its results in the [live track record](record/README.md) and rebuilds the public page. A web service with the same page is packaged with Docker and tested on every push. It is not hosted on a cloud platform yet.

## What it does today

1. Downloads hourly prices for every zone from a free public API.
2. Checks every day of data before saving it (right number of hours, no gaps, no absurd prices).
3. Stores the prices in a small SQLite database. Running it twice never creates duplicates.
4. Scores two simple baseline forecasts on the stored history.
5. Tests two models against the baseline by replaying the past one day at a time.
6. Tests what the forecast is worth for a real decision: picking the cheapest hours to run something.
7. Every morning, on its own: downloads new prices, scores the earlier forecasts, forecasts tomorrow, and publishes both.
8. Publishes a readable page with charts on GitHub Pages, rebuilt after every run.
9. Serves the same page and the raw numbers through a small web service.

## Run it

You need Python 3.10 or newer.

```bash
pip install -e ".[dev]"

pytest                                   # run the tests (no internet needed)
python -m elpris backfill --days 730     # download two years (30 to 45 minutes)
python -m elpris backtest                # score the baselines
python -m elpris compare --test-days 180 # test the models against the baseline
python -m elpris compare --test-days 180 --save record   # same, and save the result for the web page
python -m elpris plan --test-days 180    # test what the forecast is worth for picking cheap hours
python -m elpris plan --test-days 180 --save record      # same, and save the result for the web page
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

## What the forecast is worth

A lower error is not the goal. A better decision is. So the forecast is also tested on one decision that a home battery, a water heater or a heat pump has to make every day: which hours to run.

The test (`python -m elpris plan`) replays the same past days as above. Each day, a home must place 4 hours of electricity use. Four ways of picking the hours are compared, and each one is charged the real price of the hours it picked:

| Plan | How it picks the 4 hours |
| --- | --- |
| No planning | It does not pick. Use is spread over the day and pays the day's average price |
| Yesterday's cheapest hours | The hours that were cheapest yesterday. Needs no model |
| The forecast's cheapest hours | The hours the model says will be cheapest |
| Perfect hindsight | The hours that really were cheapest. Impossible in advance, shown as the limit |

The fair question is not "does planning save money". Any planning does. It is "does the forecast pick better hours than yesterday's prices would". The answer is checked the same way as the model itself, with a 95% range over the test days, and can come out as "not proven". The result is in `record/plan.csv` and on the public page.

Result on 180 days (9 April to 5 October 2026). Average price paid, in SEK per kWh:

| Zone | No planning | Yesterday's hours | Forecast's hours | Perfect hindsight | Forecast against yesterday's hours |
| --- | --- | --- | --- | --- | --- |
| SE1 | 0.3739 | 0.2903 | 0.2916 | 0.1831 | not proven (cheaper on 50 days, dearer on 49) |
| SE2 | 0.4000 | 0.3153 | 0.3176 | 0.1956 | not proven (cheaper on 57 days, dearer on 52) |
| SE3 | 0.7064 | 0.4391 | 0.4191 | 0.3268 | forecast is cheaper (70 days against 28) |
| SE4 | 0.9518 | 0.5334 | 0.4966 | 0.3852 | forecast is cheaper (66 days against 25) |

How to read this honestly:

- Any planning helps a lot. It cut the price paid by 21% to 22% in the north and by 38% to 48% in the south.
- In the two southern zones the forecast picked cheaper hours than yesterday's prices did, by about 5% and 7%, and the lead holds up over 180 days.
- In the two northern zones the forecast added nothing. Yesterday's cheapest hours were just as good.
- So the forecast earns its place where prices swing the most, and a simple rule is enough where they do not.
- Perfect hindsight is still 22% to 37% cheaper than the forecast. There is a lot of room left.

## The daily run

A scheduled GitHub Actions job (`.github/workflows/daily.yml`) runs every morning at 05:17 UTC, hours before the next day's real prices are published. GitHub sometimes starts scheduled jobs late or skips one, so the job has two backup start times, 06:47 and 08:17 UTC. A forecast is written only once, so the backups change nothing when the first run worked.

1. It restores the price database from the previous run and downloads whatever is new.
2. It scores every earlier forecast whose real prices are now known.
3. It retrains the model on all history and forecasts tomorrow.
4. It commits the forecast and the scores to `record/`.

What keeps the record honest:

- A forecast is written once. Code refuses to overwrite a day that is already recorded, and a test checks this.
- The forecast for a day is identical whether or not that day's real prices are already in the database. A test checks this too.
- A forecast is only recorded before 12:00 Swedish time the day before, about an hour before the real prices come out. After that the code records nothing, whoever starts the run. A test checks this.
- The record lives in git, so every change to it has a timestamp and a visible history.
- If the job fails, GitHub shows a red run and sends an email. A missing day stays missing. It is not filled in afterwards.
- No verdict, good or bad, is given before 14 days have been scored. A few days cannot tell skill from luck.

## The public page

After every daily run, and after every push, a workflow (`.github/workflows/pages.yml`) builds the page as plain files and publishes it on GitHub Pages. Plain files load at once and cannot go down with a server, which suits data that changes once a day.

Build it on your own machine:

```bash
python -m elpris site --record-dir record --out site
```

Then open `site/index.html` in a browser.

## The web service

A FastAPI service with five addresses:

| Address | What it returns |
| --- | --- |
| `/` | The home page: tomorrow's forecast as a chart, the last forecast against the real price, and the score so far (add `?zone=SE4` for another price area) |
| `/forecast?zone=SE3` | The newest forecast for a zone, hour by hour (add `&date=YYYY-MM-DD` for an older one) |
| `/scores` | Every scored day (add `?zone=SE3` to filter) |
| `/summary` | Totals per zone, and whether the lead is proven |
| `/health` | A quick "I am alive" answer for the hosting platform |

Run it on your own machine:

```bash
uvicorn elpris.api:app --reload
```

Then open http://localhost:8000. Or run it with Docker:

```bash
docker build -t elpris-api .
docker run -p 8080:8080 elpris-api
```

How it is designed:

- **The home page is written for someone who has never seen the project.** It says "simple guess" and "average miss", not "baseline" and "MAE", and it explains each term.
- **Every chart can be read three ways:** by eye, by pointing at it or using the arrow keys, and as a table. Colours were checked for colour-blind readers.
- **It stores nothing.** It reads the two record files that the daily run publishes on GitHub. So it can be restarted, replaced or scaled to zero without losing anything.
- **It asks GitHub at most once every ten minutes.** If a refresh fails, it keeps serving the last good copy.
- **The image does not run as root**, and it holds only the web service, not the tests or the data.
- **Every push builds the image and checks that the container answers.** A broken Dockerfile is caught before it is deployed.

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
| `src/elpris/schedule.py` | Pick the cheapest hours from a forecast and measure what that was worth |
| `src/elpris/record.py` | Keep the public record of forecasts and scores |
| `src/elpris/api.py` | The web service |
| `src/elpris/page.py` | The home page, in plain words |
| `src/elpris/charts.py` | The charts, drawn as plain SVG and HTML with no chart library |
| `Dockerfile` | Package the web service as a container image |
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
- [x] Step 3: daily scheduled run, public track record, public page, web service and Docker image
- [x] Decision test: what the forecast is worth for picking the cheapest hours
- [ ] Later: host the Docker image on a cloud platform
- [ ] Step 4: 30 days of live results, and weather forecasts as model inputs

## Data

Prices come from the public API at [elprisetjustnu.se](https://www.elprisetjustnu.se/elpris-api). Check their terms before reusing the data.
