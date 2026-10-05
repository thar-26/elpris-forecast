"""The home page: the forecast, the check against reality, and the score, in plain words.

Everything is built on the server as one HTML document. The only script on the
page is the small hover readout for the charts.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from . import charts, config, record
from .features import LOCAL_TIMEZONE

PLACES = {"SE1": "Luleå", "SE2": "Sundsvall", "SE3": "Stockholm", "SE4": "Malmö"}
DEFAULT_ZONE = "SE3"
UNIT = "öre"
ORE_PER_KRONA = 100

MODEL = "Forecast"
GUESS = "Simple guess"
REAL = "Real price"

VERDICT_WORDS = {
    "beats baseline": "Forecast is reliably closer",
    "not proven": "Too early to say",
    "worse": "Simple guess is reliably closer",
}


def e(text) -> str:
    return html.escape(str(text))


def ore(value) -> str:
    return charts.format_value(float(value) * ORE_PER_KRONA)


def nice_date(day: str, weekday: bool = True) -> str:
    stamp = pd.Timestamp(day)
    text = f"{stamp.day} {stamp.strftime('%B')}"
    return f"{stamp.strftime('%A')} {text}" if weekday else text


def day_word(day: str, now: datetime) -> str:
    today = now.astimezone(ZoneInfo(LOCAL_TIMEZONE)).date()
    target = pd.Timestamp(day).date()
    if target == today + timedelta(days=1):
        return "Tomorrow"
    if target == today:
        return "Today"
    return "Newest forecast"


def local_hours(hour_utc: pd.Series) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(hour_utc, utc=True)).tz_convert(LOCAL_TIMEZONE)


def hour_range(stamp: pd.Timestamp) -> str:
    return f"{stamp:%H:%M} to {(stamp + pd.Timedelta(hours=1)):%H:%M}"


def panel(inner: str) -> str:
    return f'<div class="panel">{inner}</div>'


# ---------------------------------------------------------------- sections


def zone_link(code: str, static: bool) -> str:
    """Where the link for a price area points: a query on the live service, a file on the static site."""
    return f"{code.lower()}.html" if static else f"/?zone={code}"


def areas_nav(forecasts: pd.DataFrame, newest: str | None, zone: str, static: bool = False) -> str:
    items = []
    for code in config.ZONES:
        average = ""
        if newest is not None:
            rows = forecasts[(forecasts["zone"] == code) & (forecasts["delivery_date"] == newest)]
            if not rows.empty:
                average = f'<span class="area-price">{ore(rows["forecast_sek_per_kwh"].mean())} {UNIT}</span>'
        current = ' aria-current="page"' if code == zone else ""
        items.append(
            f'<li><a href="{zone_link(code, static)}"{current}><span class="area-name"><b>{code}</b> {e(PLACES[code])}</span>'
            f"{average}</a></li>"
        )
    note = "<p class=\"areas-note\">Average forecast price per kWh</p>" if newest is not None else ""
    return (
        '<nav class="areas" aria-label="Price areas"><p class="areas-title">Price areas, north to south</p>'
        f'<ol>{"".join(items)}</ol>{note}</nav>'
    )


def forecast_section(forecasts: pd.DataFrame, zone: str, now: datetime, static: bool = False) -> str:
    rows = forecasts[forecasts["zone"] == zone]
    if rows.empty:
        return panel(
            f"<h2>{e(PLACES[zone])} ({zone})</h2>"
            "<p>No forecast has been made for this area yet. The first one appears after the next morning run.</p>"
        )
    day = rows["delivery_date"].max()
    rows = rows[rows["delivery_date"] == day].sort_values("hour_utc")
    hours = local_hours(rows["hour_utc"])
    prices = (rows["forecast_sek_per_kwh"] * ORE_PER_KRONA).tolist()
    low, high = min(range(len(prices)), key=prices.__getitem__), max(range(len(prices)), key=prices.__getitem__)
    made = pd.Timestamp(rows["made_at_utc"].iloc[0]).tz_convert(LOCAL_TIMEZONE)

    facts = (
        '<dl class="facts">'
        f"<div><dt>Average for the day</dt><dd>{charts.format_value(sum(prices) / len(prices))} <small>{UNIT}</small></dd></div>"
        f"<div><dt>Cheapest hour</dt><dd>{charts.format_value(prices[low])} <small>{UNIT}</small></dd>"
        f"<dd class=\"when\">{hour_range(hours[low])}</dd></div>"
        f"<div><dt>Most expensive hour</dt><dd>{charts.format_value(prices[high])} <small>{UNIT}</small></dd>"
        f"<dd class=\"when\">{hour_range(hours[high])}</dd></div>"
        "</dl>"
    )
    chart = charts.line_chart(
        [{"name": MODEL, "values": prices}],
        [f"{h:%H}" for h in hours],
        unit=UNIT,
        description=f"Forecast price for each hour of {nice_date(day)} in {PLACES[zone]}",
        long_labels=[hour_range(h) for h in hours],
        x_title="Hour of the day, Swedish time",
        width=600,
        height=280,
    )
    return panel(
        # a saved page is read on other days too, so it never says "tomorrow"
        f"<h2>{'Forecast for' if static else day_word(day, now) + ','} {nice_date(day)}: {e(PLACES[zone])} ({zone})</h2>"
        f"{facts}{chart}"
        f'<p class="note">Forecast made {made.day} {made:%B} at {made:%H:%M}. Prices are spot prices in öre per kWh '
        "(100 öre = 1 krona). Your bill adds taxes, grid fees and your supplier's margin.</p>"
    )


def check_section(forecasts: pd.DataFrame, scores: pd.DataFrame, actuals: pd.DataFrame, zone: str) -> str:
    title = "<h2>How close was the last forecast?</h2>"
    explain = (
        f"<p>Each forecast is compared with a <b>simple guess</b>: that every hour will cost the same as it did "
        "the day before. A forecast is only worth having if it gets closer to the real price than that.</p>"
    )
    mine = scores[scores["zone"] == zone]
    if mine.empty:
        return (
            f'<section>{title}{explain}<p class="empty">Nothing to check yet for {e(PLACES[zone])}. '
            "The first result appears the morning after the first forecast.</p></section>"
        )

    last = mine.sort_values("delivery_date").iloc[-1]
    day = last["delivery_date"]
    winner = "The forecast was closer" if last["model_won"] else "The simple guess was closer"
    sentence = (
        f"<p>On {nice_date(day)} in {e(PLACES[zone])}, the forecast missed the real price by "
        f"<b>{ore(last['mae_model'])} {UNIT}</b> on average. The simple guess missed by "
        f"<b>{ore(last['mae_baseline'])} {UNIT}</b>. {winner} that day.</p>"
    )

    rows = forecasts[(forecasts["zone"] == zone) & (forecasts["delivery_date"] == day)].sort_values("hour_utc")
    real = actuals[actuals["zone"] == zone]
    merged = rows.merge(real, on=["zone", "hour_utc"], how="left")
    chart = ""
    if not merged.empty and merged["sek_per_kwh"].notna().all():
        hours = local_hours(merged["hour_utc"])
        chart = panel(
            charts.line_chart(
                [
                    {"name": MODEL, "values": (merged["forecast_sek_per_kwh"] * ORE_PER_KRONA).tolist()},
                    {"name": GUESS, "values": (merged["baseline_sek_per_kwh"] * ORE_PER_KRONA).tolist()},
                    {"name": REAL, "values": (merged["sek_per_kwh"] * ORE_PER_KRONA).tolist()},
                ],
                [f"{h:%H}" for h in hours],
                unit=UNIT,
                description=f"Forecast, simple guess and real price for each hour of {nice_date(day)} in {PLACES[zone]}",
                long_labels=[hour_range(h) for h in hours],
                x_title="Hour of the day, Swedish time",
            )
        )
    return f"<section>{title}{explain}{sentence}{chart}</section>"


def score_section(scores: pd.DataFrame, zone: str) -> str:
    title = "<h2>The score so far</h2>"
    if scores.empty:
        return (
            f'<section>{title}<p class="empty">No days have been checked yet. This section fills in one day at a '
            "time, starting the morning after the first forecast.</p></section>"
        )

    totals = record.summarise(scores)
    days = scores["delivery_date"].nunique()
    bars = charts.paired_bars(
        [
            {
                "label": f'{row["zone"]} {PLACES[row["zone"]]}',
                "values": (row["mae_model"] * ORE_PER_KRONA, row["mae_baseline"] * ORE_PER_KRONA),
            }
            for row in totals
        ],
        (MODEL, GUESS),
        unit=UNIT,
        description="Average miss of the forecast and of the simple guess, for each price area",
    )
    verdicts = "".join(
        f"<tr><td>{row['zone']} {e(PLACES[row['zone']])}</td>"
        f"<td>{row['days_model_won']} of {row['days_scored']}</td>"
        f"<td>{e(VERDICT_WORDS[row['verdict']])}</td></tr>"
        for row in totals
    )
    table = (
        '<div class="scroll"><table class="verdicts"><thead><tr><th>Price area</th>'
        "<th>Days the forecast was closer</th><th>Verdict</th></tr></thead>"
        f"<tbody>{verdicts}</tbody></table></div>"
    )

    trend = ""
    mine = scores[scores["zone"] == zone].sort_values("delivery_date")
    if len(mine) >= 3:
        labels = [f"{pd.Timestamp(d).day} {pd.Timestamp(d):%b}" for d in mine["delivery_date"]]
        trend = "<h3>Day by day in " + e(PLACES[zone]) + "</h3>" + panel(
            charts.line_chart(
                [
                    {"name": MODEL, "values": (mine["mae_model"] * ORE_PER_KRONA).tolist()},
                    {"name": GUESS, "values": (mine["mae_baseline"] * ORE_PER_KRONA).tolist()},
                ],
                labels,
                unit=UNIT,
                description=f"Average miss per day in {PLACES[zone]}, forecast and simple guess",
                tick_every=-(-len(labels) // 8),  # at most eight date labels
                long_labels=[nice_date(d) for d in mine["delivery_date"]],
                x_title="Each point is one day. Lower is better.",
                height=260,
            )
        )

    return (
        f"<section>{title}<p>{days} day{'s' if days != 1 else ''} checked since "
        f"{nice_date(scores['delivery_date'].min(), weekday=False)}. The bars show how far off each method was "
        f"on average. Shorter is better.</p>{panel(bars)}{table}"
        '<p class="note">"Too early to say" means the lead could still be luck. A few good days prove nothing, '
        f"and it takes weeks to settle.</p>{trend}</section>"
    )


def backtest_section(backtest: pd.DataFrame) -> str:
    if backtest.empty:
        return ""
    model = backtest[backtest["method"] == "ridge"].set_index("zone")
    guess = backtest[backtest["method"] == "same_hour_yesterday"].set_index("zone")
    zones = [z for z in config.ZONES if z in model.index and z in guess.index]
    if not zones:
        return ""
    days = int(model.loc[zones[0], "days"])
    first, last = backtest["first_day"].iloc[0], backtest["last_day"].iloc[0]
    gains = [float(model.loc[z, "gain_pct"]) for z in zones]
    proven = all(model.loc[z, "verdict"] == "beats baseline" for z in zones)
    if proven:
        result = (
            f"The forecast's average miss was {min(gains):.0f}% to {max(gains):.0f}% smaller than the simple "
            "guess, and the lead held up in every price area."
        )
    else:
        result = "The lead over the simple guess did not hold up in every price area."
    bars = charts.paired_bars(
        [
            {
                "label": f"{z} {PLACES[z]}",
                "values": (
                    float(model.loc[z, "mae_sek_per_kwh"]) * ORE_PER_KRONA,
                    float(guess.loc[z, "mae_sek_per_kwh"]) * ORE_PER_KRONA,
                ),
            }
            for z in zones
        ],
        (MODEL, GUESS),
        unit=UNIT,
        description=f"Average miss over {days} past days, forecast and simple guess, for each price area",
    )
    return (
        f"<section><h2>Tested on {days} past days first</h2>"
        f"<p>Before the first live forecast, the method was replayed over {days} past days, "
        f"{nice_date(first, weekday=False)} to {nice_date(last, weekday=False)} {pd.Timestamp(last).year}. "
        "Each day was forecast using only the days before it, exactly as it runs now. "
        f"{result}</p>{panel(bars)}</section>"
    )


HOW_IT_WORKS = """
<section><h2>How it works</h2>
<ol class="steps">
<li><b>Every morning</b>, at about 07:20 Swedish time, it downloads the newest prices.</li>
<li><b>It checks itself.</b> Any earlier forecast whose real prices are now known is compared with them, and the result is saved.</li>
<li><b>It forecasts the next day</b>, hour by hour, using only prices up to the end of today.</li>
<li><b>It publishes both.</b> A forecast is written once and never changed afterwards.</li>
</ol>
<p>Nobody starts it by hand. If a morning run fails, that day is simply missing from the record.</p>
</section>
"""

WORDS = """
<section><h2>Words used on this page</h2>
<dl class="words">
<dt>Price area</dt><dd>Sweden is split into four areas, SE1 in the north to SE4 in the south. Each has its own electricity price, and the south is usually more expensive.</dd>
<dt>Spot price</dt><dd>The price set on the power market for each hour of the next day. It is published around 13:00 the day before.</dd>
<dt>Simple guess</dt><dd>The assumption that each hour tomorrow will cost what it cost today. It needs no model, so it is the bar a forecast has to clear.</dd>
<dt>Average miss</dt><dd>How far a forecast was from the real price, averaged over the hours of a day. A miss of 20 öre means it was 20 öre off in a typical hour.</dd>
<dt>Too early to say</dt><dd>The forecast may be ahead, but not by enough days to rule out luck.</dd>
</dl>
</section>
"""

STYLE = """
:root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--border:rgba(11,11,11,.10);--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;color-scheme:light}
@media(prefers-color-scheme:dark){:root{--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;
color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:3rem 1.25rem 4rem}
h1{font-size:clamp(2rem,5.2vw,2.9rem);line-height:1.08;letter-spacing:-.025em;margin:0 0 1rem;max-width:16ch}
h2{font-size:1.45rem;line-height:1.2;letter-spacing:-.01em;margin:0 0 .75rem}
h3{font-size:1.05rem;margin:2rem 0 .5rem}
p{margin:0 0 1rem;max-width:68ch}
.lead{font-size:1.2rem;color:var(--ink2);max-width:60ch}
section{margin-top:3.5rem}
a{color:inherit;text-underline-offset:3px}
a:focus-visible,svg:focus-visible,summary:focus-visible{outline:2px solid var(--series-1);outline-offset:3px;border-radius:4px}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1.25rem 1.25rem 1rem}
.panel h2{margin-bottom:1rem}
.now{display:grid;grid-template-columns:230px minmax(0,1fr);gap:1.75rem;margin-top:2.5rem;align-items:start}
.areas-title,.areas-note{font-size:.85rem;color:var(--ink2);margin:0 0 .6rem}
.areas-note{margin:.6rem 0 0}
.areas ol{list-style:none;margin:0;padding:0;border-left:2px solid var(--axis)}
.areas a{display:flex;justify-content:space-between;align-items:baseline;gap:.75rem;padding:.7rem .25rem .7rem 1rem;
margin-left:-2px;border-left:2px solid transparent;text-decoration:none;position:relative}
.areas a::before{content:"";position:absolute;left:-6px;top:1.15rem;width:10px;height:10px;border-radius:50%;
background:var(--page);border:2px solid var(--axis)}
.areas a:hover{background:var(--surface)}
.areas a[aria-current]{border-left-color:var(--series-1);background:var(--surface)}
.areas a[aria-current]::before{background:var(--series-1);border-color:var(--series-1)}
.area-name{color:var(--ink2)}.area-name b{color:var(--ink);margin-right:.25rem}
.area-price{font-variant-numeric:tabular-nums;white-space:nowrap}
.facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin:0 0 1.25rem}
.facts dt{font-size:.85rem;color:var(--ink2)}
.facts dd{margin:0;font-size:1.7rem;font-weight:650;line-height:1.2}
.facts dd small{font-size:.9rem;font-weight:400;color:var(--ink2)}
.facts dd.when{font-size:.85rem;font-weight:400;color:var(--ink2)}
.note{font-size:.88rem;color:var(--ink2);margin-top:.9rem}
.empty{border-left:2px solid var(--axis);padding:.4rem 0 .4rem 1rem;color:var(--ink2)}
figure.chart{margin:0}
.scroll{overflow-x:auto}
.plot-box{position:relative}
svg.plot{display:block;width:100%;height:auto}
.grid,.axis,.crosshair{stroke-width:1;vector-effect:non-scaling-stroke}
.grid{stroke:var(--grid)}.axis{stroke:var(--axis)}
.tick{fill:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;vector-effect:non-scaling-stroke}
.area{stroke:none;fill-opacity:.1}
.dot{stroke:var(--surface);stroke-width:2}
.line.s1{stroke:var(--series-1)}.line.s2{stroke:var(--series-2)}.line.s3{stroke:var(--series-3)}
.area.s1,.dot.s1{fill:var(--series-1)}.dot.s2{fill:var(--series-2)}.dot.s3{fill:var(--series-3)}
.bars{list-style:none;margin:.25rem 0 0;padding:0;display:grid;gap:.85rem}
.bars li{display:grid;grid-template-columns:9.5rem minmax(0,1fr);gap:.2rem 1rem;align-items:center}
.bar-label{font-size:.9rem}
.bar-pair{display:grid;gap:2px;border-left:1px solid var(--axis)}
.bar-row{display:flex;align-items:center;gap:.5rem}
.bar{display:block;height:12px;min-width:2px;border-radius:0 4px 4px 0}
.bar.s1{background:var(--series-1)}.bar.s2{background:var(--series-2)}
.bar-row:hover .bar{opacity:.8}
.bar-value{font-size:.8rem;color:var(--ink2);white-space:nowrap;font-variant-numeric:tabular-nums}
.crosshair{stroke:var(--axis);display:none}.hover-dot{display:none}
.hovering .crosshair,.hovering .hover-dot{display:block}
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:.35rem 1.25rem;margin:0 0 .6rem;padding:0;font-size:.88rem;color:var(--ink2)}
.legend li,.tip-row{display:flex;align-items:center;gap:.45rem}
.key{display:inline-block;width:16px;height:2px;border-radius:1px}.key.box{width:10px;height:10px;border-radius:2px}
.key.s1{background:var(--series-1)}.key.s2{background:var(--series-2)}.key.s3{background:var(--series-3)}
.tooltip{position:absolute;top:10px;background:var(--surface);border:1px solid var(--border);border-radius:8px;
padding:.5rem .7rem;font-size:.85rem;pointer-events:none;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.14)}
.tip-head{color:var(--ink2);margin-bottom:.2rem}.tip-row span:last-child{color:var(--ink2)}
.table-view{margin-top:.6rem;font-size:.88rem}.table-view summary{cursor:pointer;color:var(--ink2)}
table{border-collapse:collapse;width:100%;margin:.6rem 0 0;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:.35rem .6rem;border-bottom:1px solid var(--grid)}
th{font-weight:600;border-bottom-color:var(--axis)}th:first-child,td:first-child{text-align:left}
.verdicts{margin-top:1rem}.verdicts th,.verdicts td{text-align:left}
.steps{padding-left:1.25rem;max-width:68ch}.steps li{margin-bottom:.5rem}
.words dt{font-weight:650;margin-top:.9rem}.words dd{margin:0;max-width:68ch;color:var(--ink2)}
footer{margin-top:4rem;padding-top:1.25rem;border-top:1px solid var(--grid);font-size:.88rem;color:var(--ink2)}
@media(max-width:760px){.now{grid-template-columns:minmax(0,1fr)}.facts{grid-template-columns:1fr 1fr}
.areas ol{display:grid;grid-template-columns:1fr 1fr;border-left:0;gap:.25rem}
.areas a{border:1px solid var(--border);border-radius:8px;margin:0;padding:.6rem .75rem}.areas a::before{display:none}
.areas a[aria-current]{border-color:var(--series-1)}
.tick{font-size:22px}.x-title{display:none}.long-x .x-alt{display:none}
.bars li{grid-template-columns:minmax(0,1fr)}.panel{padding:1rem 1rem .9rem}}
"""


def render(data: dict, zone: str = DEFAULT_ZONE, now: datetime | None = None, static: bool = False) -> str:
    """Build the whole page. `data` holds the four record tables.

    static=True builds the version that is saved as files and published on GitHub Pages:
    links point to files, and dates are written out instead of saying "tomorrow".
    """
    now = now or datetime.now().astimezone()
    forecasts, scores = data["forecasts"], data["scores"]
    actuals, backtest = data["actuals"], data["backtest"]
    newest = forecasts["delivery_date"].max() if not forecasts.empty else None

    if static:
        updated = now.astimezone(ZoneInfo(LOCAL_TIMEZONE))
        extra = (
            f"<p>Page updated {updated.day} {updated:%B} {updated.year} at {updated:%H:%M} Swedish time. "
            'The numbers behind it are in the <a href="https://github.com/thar-26/elpris-forecast/tree/main/record">'
            "record folder</a>.</p>"
        )
    else:
        extra = (
            '<p>The same numbers for programs: <a href="/summary">/summary</a>, <a href="/scores">/scores</a>, '
            f'<a href="/forecast?zone={zone}">/forecast?zone={zone}</a>, and the <a href="/docs">API guide</a>.</p>'
        )

    body = (
        "<header><h1>Tomorrow's electricity price in Sweden</h1>"
        '<p class="lead">Every morning a model forecasts the hourly price for the next day, in each of Sweden\'s '
        "four price areas. When the real prices come in, the forecast is checked against them, and the result is "
        "published here, good or bad.</p></header>"
        f'<div class="now">{areas_nav(forecasts, newest, zone, static)}'
        f"{forecast_section(forecasts, zone, now, static)}</div>"
        f"{check_section(forecasts, scores, actuals, zone)}"
        f"{score_section(scores, zone)}"
        f"{backtest_section(backtest)}"
        f"{HOW_IT_WORKS}{WORDS}"
        "<footer><p>Built by Tharun Kumar Marada. The code, the tests and the full record are on "
        '<a href="https://github.com/thar-26/elpris-forecast">GitHub</a>. '
        'Prices come from <a href="https://www.elprisetjustnu.se/elpris-api">elprisetjustnu.se</a>.</p>'
        f"{extra}</footer>"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Tomorrow's electricity price in Sweden</title>"
        '<meta name="description" content="A daily forecast of Swedish electricity prices, checked against the real prices.">'
        f"<style>{STYLE}</style></head><body><main class=\"wrap\">{body}</main>"
        f"<script>{charts.HOVER_SCRIPT}</script></body></html>"
    )


def build_site(data: dict, out_dir, now: datetime | None = None) -> list:
    """Save the page for every price area as plain files. index.html is the default area."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for code in config.ZONES:
        text = render(data, zone=code, now=now, static=True)
        names = [f"{code.lower()}.html"] + (["index.html"] if code == DEFAULT_ZONE else [])
        for name in names:
            (out / name).write_text(text, encoding="utf-8")
            written.append(out / name)
    (out / ".nojekyll").write_text("", encoding="utf-8")  # tells GitHub Pages to serve the files as they are
    return written
