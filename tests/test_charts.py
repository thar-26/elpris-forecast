import json
import re

from elpris import charts


def test_axis_values_are_round_numbers_that_cover_the_data():
    assert charts.nice_ticks(0, 147) == [0, 50, 100, 150]
    assert charts.nice_ticks(0, 0.8)[0] == 0 and charts.nice_ticks(0, 0.8)[-1] >= 0.8
    assert charts.nice_ticks(-12, 90)[0] <= -12


def test_values_are_whole_numbers_from_ten_upwards():
    assert charts.format_value(146.6) == "147"
    assert charts.format_value(7.25) == "7.2" or charts.format_value(7.25) == "7.3"
    assert charts.format_value(float("nan")) == ""


def test_line_chart_draws_every_series_and_carries_its_numbers():
    svg = charts.line_chart(
        [{"name": "Forecast", "values": [10, 20, 30]}, {"name": "Real price", "values": [12, 18, 33]}],
        ["00", "01", "02"],
        unit="öre",
        description="A test chart",
        tick_every=1,
    )
    assert svg.count('class="line') == 2
    assert 'class="legend"' in svg                       # two series, so a legend
    assert "Show these numbers as a table" in svg        # readable without colour or hovering
    data = json.loads(re.search(r'data-chart="([^"]*)"', svg).group(1).replace("&quot;", '"'))
    assert data["names"] == ["Forecast", "Real price"]
    assert data["values"][1] == ["12", "18", "33"]
    assert len(data["x"]) == 3


def test_a_single_series_gets_no_legend():
    svg = charts.line_chart([{"name": "Forecast", "values": [10, 20, 30]}], ["a", "b", "c"], unit="öre", description="x")
    assert 'class="legend"' not in svg
    assert 'class="area' in svg


def test_line_chart_with_nothing_to_draw_is_empty():
    assert charts.line_chart([{"name": "Forecast", "values": [None, None]}], ["a", "b"], unit="öre", description="x") == ""


def test_names_and_labels_are_escaped():
    svg = charts.line_chart(
        [{"name": "<b>bad</b>", "values": [1, 2]}, {"name": "ok", "values": [2, 3]}],
        ["a", "b"], unit="öre", description='say "hi"',
    )
    assert "<b>bad</b>" not in svg
    bars = charts.paired_bars([{"label": "<i>x</i>", "values": (1, 2)}], ("a", "b"), unit="öre", description="x")
    assert "<i>x</i>" not in bars


def test_paired_bars_scale_to_the_largest_value():
    bars = charts.paired_bars(
        [{"label": "SE1 Luleå", "values": (20, 40)}, {"label": "SE4 Malmö", "values": (30, 10)}],
        ("Forecast", "Simple guess"), unit="öre", description="x",
    )
    widths = [float(w) for w in re.findall(r"\* ([0-9.]+)\)", bars)]
    assert widths == [0.5, 1.0, 0.75, 0.25]
    assert "40 öre" in bars and "SE4 Malmö" in bars
