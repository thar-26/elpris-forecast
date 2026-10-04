"""Charts drawn as plain SVG on the server. No chart library.

Two forms are enough for this project:

    line_chart    prices or errors over time, up to three series
    paired_bars   two numbers side by side for each price area

Every chart comes with a legend (when there is more than one series), a hover
readout, and a table of the same numbers, so nothing can only be read by colour.
Colours are set in the page's CSS as --series-1, --series-2 and --series-3.
"""

from __future__ import annotations

import html
import json
import math

WIDTH = 760


def nice_ticks(low: float, high: float, target: int = 4) -> list[float]:
    """Round axis values such as 0, 50, 100, 150 that cover low..high."""
    if high <= low:
        high = low + 1
    raw = (high - low) / target
    magnitude = 10 ** math.floor(math.log10(raw))
    step = magnitude
    for multiple in (1, 2, 2.5, 5, 10):
        step = multiple * magnitude
        if raw <= step:
            break
    ticks = [math.floor(low / step) * step]
    while ticks[-1] < high:
        ticks.append(round(ticks[-1] + step, 6))
    return ticks


def format_value(value: float) -> str:
    """Whole numbers once a value is 10 or more, one decimal below that."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return f"{value:.0f}" if abs(value) >= 10 else f"{value:.1f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in rows)
    return (
        "<details class=\"table-view\"><summary>Show these numbers as a table</summary>"
        f"<div class=\"scroll\"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></details>"
    )


def line_chart(
    series: list[dict],
    labels: list[str],
    *,
    unit: str,
    description: str,
    tick_every: int = 3,
    long_labels: list[str] | None = None,
    x_title: str = "",
    height: int = 300,
    width: int = WIDTH,
) -> str:
    """A line chart with up to three series.

    series: [{"name": "Forecast", "values": [..]}, ...]; a value may be None.
    labels: one short label per x position, used on the axis.
    long_labels: one longer label per x position, used in the hover readout and the table.
    """
    series = series[:3]
    long_labels = long_labels or labels
    count = len(labels)
    known = [v for s in series for v in s["values"] if v is not None]
    if not known or count < 2:
        return ""

    left, right, top, bottom = 56, 20, 40, 44
    plot_w, plot_h = width - left - right, height - top - bottom
    ticks = nice_ticks(min(0.0, min(known)), max(known))
    low, high = ticks[0], ticks[-1]
    whole = all(float(t).is_integer() for t in ticks)

    def tick_text(value: float) -> str:
        return f"{value:.0f}" if whole else f"{value:g}"

    def x_at(index: int) -> float:
        return round(left + plot_w * index / (count - 1), 1)

    def y_at(value: float) -> float:
        return round(top + plot_h * (1 - (value - low) / (high - low)), 1)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" tabindex="0" '
        f'aria-label="{html.escape(description)}" class="plot">'
    ]

    # grid, y axis labels, zero line
    for tick in ticks:
        y = y_at(tick)
        css = "axis" if tick == 0 else "grid"
        parts.append(f'<line class="{css}" x1="{left}" x2="{width - right}" y1="{y}" y2="{y}"/>')
        parts.append(
            f'<text class="tick" x="{left - 8}" y="{y}" text-anchor="end" dominant-baseline="middle">'
            f"{tick_text(tick)}</text>"
        )
    parts.append(
        f'<text class="tick" x="{left - 8}" y="2" text-anchor="end" dominant-baseline="hanging">{html.escape(unit)}</text>'
    )

    # x axis labels
    for position, index in enumerate(range(0, count, tick_every)):
        css = "tick x-alt" if position % 2 else "tick"
        parts.append(
            f'<text class="{css}" x="{x_at(index)}" y="{top + plot_h + 8}" text-anchor="middle" '
            f'dominant-baseline="hanging">{html.escape(labels[index])}</text>'
        )
    if x_title:
        parts.append(
            f'<text class="tick x-title" x="{left + plot_w / 2}" y="{height - 4}" text-anchor="middle">'
            f"{html.escape(x_title)}</text>"
        )

    # one soft area under a lone series, then the lines, then the end dots
    pixel_rows = []
    for number, one in enumerate(series, start=1):
        points = [(x_at(i), y_at(v)) for i, v in enumerate(one["values"]) if v is not None]
        pixel_rows.append([None if v is None else y_at(v) for v in one["values"]])
        if not points:
            continue
        path = "M" + " L".join(f"{x},{y}" for x, y in points)
        if len(series) == 1:
            base = y_at(max(low, 0.0))
            parts.append(f'<path class="area s{number}" d="{path} L{points[-1][0]},{base} L{points[0][0]},{base} Z"/>')
        parts.append(f'<path class="line s{number}" d="{path}"/>')
        parts.append(f'<circle class="dot s{number}" cx="{points[-1][0]}" cy="{points[-1][1]}" r="4.5"/>')

    # hover layer: a vertical hairline and one dot per series, moved by the page script
    parts.append(f'<line class="crosshair" x1="0" x2="0" y1="{top}" y2="{top + plot_h}"/>')
    for number in range(1, len(series) + 1):
        parts.append(f'<circle class="dot hover-dot s{number}" r="5"/>')
    parts.append("</svg>")

    legend = ""
    if len(series) > 1:
        keys = "".join(
            f'<li><span class="key s{number}"></span>{html.escape(one["name"])}</li>'
            for number, one in enumerate(series, start=1)
        )
        legend = f'<ul class="legend">{keys}</ul>'

    data = {
        "x": [x_at(i) for i in range(count)],
        "y": pixel_rows,
        "labels": long_labels,
        "names": [one["name"] for one in series],
        "values": [[None if v is None else format_value(v) for v in one["values"]] for one in series],
        "unit": unit,
        "width": width,
    }
    table = _table(
        ["", *[f'{one["name"]} ({unit})' for one in series]],
        [[long_labels[i], *[format_value(one["values"][i]) for one in series]] for i in range(count)],
    )
    long_x = " long-x" if max(len(label) for label in labels) > 3 else ""
    return (
        f'<figure class="chart{long_x}" data-chart="{html.escape(json.dumps(data), quote=True)}">'
        f'{legend}<div class="plot-box">{"".join(parts)}'
        f'<div class="tooltip" hidden></div></div>{table}</figure>'
    )


def paired_bars(rows: list[dict], names: tuple[str, str], *, unit: str, description: str) -> str:
    """Two thin horizontal bars per row, for comparing two numbers across price areas.

    rows: [{"label": "SE3 Stockholm", "values": (first, second)}, ...]
    Built from plain HTML boxes, so the labels stay readable on a phone.
    """
    if not rows:
        return ""
    biggest = max(max(row["values"]) for row in rows) or 1.0
    items = []
    for row in rows:
        bars = ""
        for number, value in enumerate(row["values"], start=1):
            share = max(0.004, value / biggest)
            text = f"{format_value(value)} {unit}"
            bars += (
                f'<div class="bar-row" title="{html.escape(names[number - 1])}: {html.escape(text)}">'
                f'<span class="bar s{number}" style="width:calc((100% - 5rem) * {share:.4f})"></span>'
                f'<span class="bar-value">{html.escape(text)}</span></div>'
            )
        items.append(f'<li><span class="bar-label">{html.escape(row["label"])}</span><div class="bar-pair">{bars}</div></li>')

    legend = (
        '<ul class="legend">'
        + "".join(
            f'<li><span class="key box s{number}"></span>{html.escape(name)}</li>'
            for number, name in enumerate(names, start=1)
        )
        + "</ul>"
    )
    table = _table(
        ["Price area", *[f"{name} ({unit})" for name in names]],
        [[row["label"], *[format_value(v) for v in row["values"]]] for row in rows],
    )
    return (
        f'<figure class="chart" aria-label="{html.escape(description)}">{legend}'
        f'<ul class="bars">{"".join(items)}</ul>{table}</figure>'
    )


# The hover readout. It moves a hairline to the nearest hour and lists every series there.
# Text is written with textContent, never as HTML. Arrow keys do the same as the pointer.
HOVER_SCRIPT = """
document.querySelectorAll('figure.chart[data-chart]').forEach(function (figure) {
  var data = JSON.parse(figure.dataset.chart);
  var svg = figure.querySelector('svg');
  var tip = figure.querySelector('.tooltip');
  var hair = figure.querySelector('.crosshair');
  var dots = figure.querySelectorAll('.hover-dot');
  var current = -1;

  function show(index) {
    current = Math.max(0, Math.min(data.x.length - 1, index));
    var x = data.x[current];
    hair.setAttribute('x1', x); hair.setAttribute('x2', x);
    figure.classList.add('hovering');
    tip.textContent = '';
    var head = document.createElement('div');
    head.className = 'tip-head';
    head.textContent = data.labels[current];
    tip.appendChild(head);
    data.names.forEach(function (name, s) {
      var y = data.y[s][current];
      dots[s].style.display = y === null ? 'none' : '';
      if (y === null) { return; }
      dots[s].setAttribute('cx', x); dots[s].setAttribute('cy', y);
      var row = document.createElement('div');
      row.className = 'tip-row';
      var key = document.createElement('span');
      key.className = 'key s' + (s + 1);
      var value = document.createElement('strong');
      value.textContent = data.values[s][current] + ' ' + data.unit;
      var label = document.createElement('span');
      label.textContent = name;
      row.appendChild(key); row.appendChild(value); row.appendChild(label);
      tip.appendChild(row);
    });
    tip.hidden = false;
    var box = svg.getBoundingClientRect();
    var left = x * box.width / data.width;
    var flip = left > box.width * 0.62;
    tip.style.left = flip ? '' : (left + 14) + 'px';
    tip.style.right = flip ? (box.width - left + 14) + 'px' : '';
  }

  function hide() { figure.classList.remove('hovering'); tip.hidden = true; current = -1; }

  svg.addEventListener('pointermove', function (event) {
    var box = svg.getBoundingClientRect();
    var x = (event.clientX - box.left) * data.width / box.width;
    var best = 0;
    data.x.forEach(function (px, i) { if (Math.abs(px - x) < Math.abs(data.x[best] - x)) { best = i; } });
    show(best);
  });
  svg.addEventListener('pointerleave', hide);
  svg.addEventListener('blur', hide);
  svg.addEventListener('focus', function () { if (current < 0) { show(0); } });
  svg.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowRight') { show(current + 1); event.preventDefault(); }
    if (event.key === 'ArrowLeft') { show(current - 1); event.preventDefault(); }
    if (event.key === 'Escape') { hide(); }
  });
});
"""
