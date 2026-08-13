"""Inline SVG chart primitives.

These are strings, so they are tested as strings: valid markup, no crashes on
degenerate input (empty series, everything zero, a single week), and the
semantic colours applied to the right marks.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from football_pool import svg


def parse(markup: str) -> ET.Element:
    """Every chart must be well-formed XML, or the page silently breaks."""
    return ET.fromstring(markup)


# -- sparkline --------------------------------------------------------------
def test_sparkline_plots_every_point():
    el = parse(svg.sparkline([1.0, 4.0, 2.0, 8.0]))
    points = el.find("polyline").get("points")
    assert len(points.split()) == 4


def test_sparkline_survives_an_empty_series():
    """Week zero: nobody has a trend yet."""
    markup = svg.sparkline([])
    assert parse(markup) is not None
    assert "polyline" not in markup


def test_sparkline_survives_a_flat_series():
    """A flat line must not divide by a zero range."""
    el = parse(svg.sparkline([5.0, 5.0, 5.0]))
    ys = [p.split(",")[1] for p in el.find("polyline").get("points").split()]
    assert len(set(ys)) == 1  # all at the same height


def test_sparkline_handles_a_single_point():
    assert parse(svg.sparkline([3.0])) is not None


def test_sparkline_is_hidden_from_screen_readers():
    """The number is in the adjacent cell; the line is decoration."""
    assert parse(svg.sparkline([1.0, 2.0])).get("aria-hidden") == "true"


# -- outlook bar ------------------------------------------------------------
def test_outlook_bar_segments_are_ordered_and_nested():
    markup = svg.outlook_bar(banked=40, guaranteed=10, ceiling=100, scale_max=100)
    el = parse(markup)
    rects = [r for r in el.iter("rect") if r.get("rx")]
    widths = [float(r.get("width")) for r in rects]
    # ceiling (220) >= floor (110) >= banked (88), on a 220px rail
    assert widths[0] >= widths[1] >= widths[2]


def test_outlook_bar_describes_itself():
    markup = svg.outlook_bar(40, 10, 100, 100)
    assert parse(markup).get("role") == "img"
    assert "banked 40" in parse(markup).get("aria-label")


def test_outlook_bar_clamps_beyond_the_scale():
    """A ceiling above the shared maximum must not overflow the rail."""
    el = parse(svg.outlook_bar(10, 0, 500, scale_max=100))
    widths = [float(r.get("width")) for r in el.iter("rect") if r.get("rx")]
    assert max(widths) <= 220


def test_outlook_bar_with_nothing_banked():
    """Preseason: everyone is at zero and the bar must still render."""
    el = parse(svg.outlook_bar(0, 0, 0, scale_max=0))
    assert el is not None


# -- contribution bar -------------------------------------------------------
def test_contribution_bar_is_proportional():
    el = parse(svg.contribution_bar([("KC", 30.0), ("SEA", 10.0)]))
    widths = [float(r.get("width")) for r in el.iter("rect")]
    assert widths[0] > widths[1] * 2


def test_contribution_bar_with_no_points_yet():
    """Before week 1 every team has contributed nothing."""
    markup = svg.contribution_bar([("KC", 0.0), ("SEA", 0.0)])
    assert parse(markup) is not None
    assert "text" not in markup  # nothing to label


def test_contribution_bar_omits_labels_on_slivers():
    """A tiny segment gets no label rather than overflowing its neighbour."""
    markup = svg.contribution_bar([("KC", 100.0), ("SEA", 0.5)])
    labels = re.findall(r"<text[^>]*>([^<]+)</text>", markup)
    assert "KC" in labels
    assert "SEA" not in labels


def test_contribution_bar_ignores_negative_values():
    el = parse(svg.contribution_bar([("KC", 10.0), ("SEA", -5.0)]))
    assert el is not None


def test_contribution_bar_cycles_the_palette():
    """More teams than palette entries must not raise."""
    parts = [(f"T{i}", 1.0) for i in range(9)]
    assert parse(svg.contribution_bar(parts)) is not None


# -- range bar and meter ----------------------------------------------------
def test_range_bar_places_the_marker_inside_the_band():
    el = parse(svg.range_bar(low=20, high=80, point=50, scale_min=0, scale_max=100))
    circle = el.find("circle")
    assert float(circle.get("cx")) == pytest.approx(100.0)


def test_range_bar_uses_the_model_colour_not_the_actual_colour():
    """A projection must never be drawn in the colour used for real results."""
    markup = svg.range_bar(20, 80, 50, 0, 100)
    assert svg.MODEL in markup
    assert svg.BANKED not in markup


def test_range_bar_with_a_degenerate_scale():
    assert parse(svg.range_bar(5, 5, 5, 5, 5)) is not None


@pytest.mark.parametrize("value, expected", [(-1.0, 0.0), (0.5, 30.0), (2.0, 60.0)])
def test_meter_clamps_to_zero_and_one(value, expected):
    el = parse(svg.meter(value))
    fill = list(el.iter("rect"))[1]
    assert float(fill.get("width")) == pytest.approx(expected)


# -- emphasis chart ---------------------------------------------------------
def test_emphasis_chart_draws_every_series():
    series = [("A", [1, 2, 3]), ("B", [2, 3, 4]), ("C", [0, 1, 2])]
    el = parse(svg.emphasis_lines(series, labels=["A"]))
    assert len(list(el.iter("polyline"))) == 3


def test_only_named_series_are_emphasised():
    series = [("A", [1, 2, 3]), ("B", [2, 3, 4])]
    markup = svg.emphasis_lines(series, labels=["A"])
    el = parse(markup)
    lead = [p for p in el.iter("polyline") if "is-lead" in (p.get("class") or "")]
    assert len(lead) == 1
    # Exactly one endpoint label, for the emphasised series.
    assert [t.text for t in el.iter("text") if t.get("class") == "trend-label"] == ["A"]


def test_every_series_carries_its_name_for_hover():
    series = [("Aunt Carol", [1, 2]), ("Cousin Mike", [2, 1])]
    titles = [t.text for t in parse(svg.emphasis_lines(series, labels=[])).iter("title")]
    assert set(titles) == {"Aunt Carol", "Cousin Mike"}


def test_emphasis_chart_survives_no_data():
    assert parse(svg.emphasis_lines([], labels=[])) is not None
    assert parse(svg.emphasis_lines([("A", [])], labels=["A"])) is not None


def test_emphasis_chart_handles_a_flat_field():
    """Week one: everyone is on the same score, so the range is zero."""
    series = [("A", [0, 0]), ("B", [0, 0])]
    assert parse(svg.emphasis_lines(series, labels=["A"])) is not None


def test_inverted_axis_puts_first_place_on_top():
    """Rank 1 should sit above rank 6."""
    series = [("Top", [1, 1]), ("Bottom", [6, 6])]
    el = parse(svg.emphasis_lines(series, labels=["Top", "Bottom"], invert=True))
    ys = {}
    for line in el.iter("polyline"):
        name = line.find("title").text
        ys[name] = float(line.get("points").split()[0].split(",")[1])
    assert ys["Top"] < ys["Bottom"]


def test_week_ticks_are_labelled():
    el = parse(svg.emphasis_lines([("A", [1, 2, 3])], labels=[], x_ticks=[5, 6, 7]))
    ticks = [t.text for t in el.iter("text") if t.get("class") == "trend-tick"]
    assert ticks == ["5", "6", "7"]


def test_close_finishes_do_not_stack_labels():
    """Two entrants a hair apart must not print over each other."""
    series = [("A", [0.0, 10.0]), ("B", [0.0, 10.05])]
    el = parse(svg.emphasis_lines(series, labels=["A", "B"]))
    ys = sorted(float(t.get("y")) for t in el.iter("text") if t.get("class") == "trend-label")
    assert ys[1] - ys[0] >= 12


def _label_ys(markup: str) -> list[float]:
    el = parse(markup)
    return sorted(
        float(t.get("y")) for t in el.iter("text") if t.get("class") == "trend-label"
    )


def test_a_tight_finish_slides_labels_back_into_the_plot():
    """Five entrants finishing within a point still fit, so the run shifts up."""
    series = [(f"E{i}", [0.0, 10.0 + i * 0.01]) for i in range(5)]
    ys = _label_ys(svg.emphasis_lines(series, labels=[n for n, _ in series], height=340))
    assert min(ys) >= 0
    assert max(ys) <= 340


def test_labels_never_get_pushed_off_the_top():
    """When a stack cannot physically fit, it must not overflow upward.

    Eight labels need ~98px of separation and a 90px chart has ~50px of plot,
    so something has to give — but running off the top of the chart, where the
    masthead is, is the one direction that must never happen.
    """
    series = [(f"E{i}", [0.0, 10.0 + i * 0.01]) for i in range(8)]
    ys = _label_ys(svg.emphasis_lines(series, labels=[n for n, _ in series], height=90))
    assert min(ys) >= 0
    # Whatever else happens, they are still separated rather than stacked.
    assert all(b - a >= 12 for a, b in zip(ys, ys[1:]))


def test_number_formatting_trims_noise():
    assert svg._fmt(1.50) == "1.5"
    assert svg._fmt(2.00) == "2"
    assert svg._fmt(1.25) == "1.25"


def test_labels_are_escaped():
    """A stray angle bracket in a name must not break the markup."""
    markup = svg.contribution_bar([("A<B>", 10.0)])
    assert "<B>" not in markup.replace("&lt;B&gt;", "")
    assert parse(markup) is not None
