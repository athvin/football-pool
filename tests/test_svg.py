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


# -- comparison chart -------------------------------------------------------
SERIES = [
    ("Brian Moore", "brian-moore", [0.0, 4.0, 9.0]),
    ("Paul Moore", "paul-moore", [0.0, 2.0, 3.0]),
    ("Brenda Moore", "brenda-moore", [0.0, 6.0, 6.5]),
]


def test_compare_chart_draws_every_entrant_once():
    el = parse(svg.compare_lines(SERIES))
    lines = el.findall(".//polyline[@class='cmp-line']")
    assert len(lines) == len(SERIES)
    assert [p.get("data-entrant") for p in lines] == [s for _, s, _ in SERIES]


def test_every_entrant_gets_a_line_a_dot_and_a_label():
    """All three carry the same slug: the picker toggles them as one unit."""
    el = parse(svg.compare_lines(SERIES))
    for _, slug, _ in SERIES:
        for tag, cls in (("polyline", "cmp-line"), ("circle", "cmp-dot"), ("text", "cmp-label")):
            found = el.findall(f".//{tag}[@data-entrant='{slug}']")
            assert len(found) == 1, f"{slug} has {len(found)} {tag}"
            assert found[0].get("class") == cls


def test_nothing_is_preselected_in_the_markup():
    """Picking is the viewer's choice, so the server must not decide it.

    With scripting off this is what you get: the whole field, evenly drawn.
    """
    markup = svg.compare_lines(SERIES)
    assert "is-picked" not in markup


def test_labels_carry_their_true_y_for_the_de_collider():
    """The browser nudges colliding labels apart and needs the original value."""
    el = parse(svg.compare_lines(SERIES))
    for text in el.findall(".//text[@class='cmp-label']"):
        assert float(text.get("data-y")) == pytest.approx(float(text.get("y")) - 4, abs=0.05)


def test_the_dot_sits_on_the_final_value():
    """A leader and a trailer must not share an endpoint height."""
    el = parse(svg.compare_lines(SERIES))
    ys = {
        c.get("data-entrant"): float(c.get("cy"))
        for c in el.findall(".//circle[@class='cmp-dot']")
    }
    # Brian finishes highest, so his dot is nearest the top (smallest y).
    assert ys["brian-moore"] < ys["brenda-moore"] < ys["paul-moore"]


def test_compare_chart_shares_the_scale_across_entrants():
    """One shared y-scale, or the lines would be uncomparable — the whole point."""
    el = parse(svg.compare_lines(SERIES))
    all_ys = [
        float(pt.split(",")[1])
        for line in el.findall(".//polyline[@class='cmp-line']")
        for pt in line.get("points").split()
    ]
    # Every series starts at 0.0, so every first point lands on the same y.
    firsts = {
        line.get("points").split()[0].split(",")[1]
        for line in el.findall(".//polyline[@class='cmp-line']")
    }
    assert len(firsts) == 1
    assert max(all_ys) > min(all_ys)


def test_compare_chart_inverts_for_rank():
    """Rank 1 belongs at the top, which is the opposite of points."""
    ranks = [("A", "a", [3.0, 1.0]), ("B", "b", [1.0, 3.0])]
    el = parse(svg.compare_lines(ranks, invert=True))
    ys = {
        c.get("data-entrant"): float(c.get("cy"))
        for c in el.findall(".//circle[@class='cmp-dot']")
    }
    # A ends first, B ends third, so A must be higher on the page.
    assert ys["a"] < ys["b"]


def test_compare_chart_survives_no_data():
    markup = svg.compare_lines([])
    assert parse(markup) is not None
    assert "cmp-line" not in markup


def test_compare_chart_skips_entrants_with_no_history():
    """Someone added mid-season has no series yet and must not draw an empty line."""
    el = parse(svg.compare_lines([("A", "a", [1.0, 2.0]), ("B", "b", [])]))
    assert len(el.findall(".//polyline[@class='cmp-line']")) == 1


def test_compare_chart_handles_a_single_week():
    """Week one: one point per entrant, and no division by a zero step."""
    el = parse(svg.compare_lines([("A", "a", [3.0]), ("B", "b", [5.0])]))
    assert len(el.findall(".//circle[@class='cmp-dot']")) == 2


def test_compare_chart_handles_a_dead_heat():
    """Everyone level: a zero span must not divide by zero."""
    el = parse(svg.compare_lines([("A", "a", [4.0, 4.0]), ("B", "b", [4.0, 4.0])]))
    assert len(el.findall(".//polyline[@class='cmp-line']")) == 2


def test_compare_chart_renders_week_ticks():
    el = parse(svg.compare_lines(SERIES, x_ticks=[1, 2, 3]))
    ticks = [t.text for t in el.findall(".//text[@class='trend-tick']")]
    assert ticks == ["1", "2", "3"]


def test_compare_chart_escapes_names_and_slugs():
    """A name is entrant-supplied data and goes into both text and an attribute."""
    markup = svg.compare_lines([('A<script>', 'a"b', [1.0, 2.0])])
    assert "<script>" not in markup
    assert parse(markup) is not None


# -- forecast charts --------------------------------------------------------
def test_finish_bar_segments_every_place():
    el = parse(svg.finish_bar([0.5, 0.3, 0.15, 0.05]))
    assert len(el.findall(".//rect")) == 4


def test_finish_bar_always_fills_the_rail():
    """Probabilities sum to one, so the bar is full width at every entrant.

    That is what lets the eye compare segment widths between rows without
    mentally rescaling each bar.
    """
    width = 320
    for probs in ([0.9, 0.1], [0.25] * 4, [1.0]):
        el = parse(svg.finish_bar(probs, width=width))
        total = sum(float(r.get("width")) for r in el.findall(".//rect"))
        # Each segment is drawn a pixel short to leave a hairline gap.
        assert total == pytest.approx(width - len(probs), abs=1.5)


def test_finish_bar_labels_only_segments_wide_enough_to_hold_one():
    el = parse(svg.finish_bar([0.94, 0.02, 0.02, 0.02]))
    labels = [t.text for t in el.findall(".//text")]
    assert labels == ["1st"]


def test_finish_bar_uses_a_sequential_ramp_not_categorical_colours():
    """Finishing position is ordinal, so first place is one end of one ramp."""
    fills = [r.get("fill") for r in parse(svg.finish_bar([0.25] * 4)).findall(".//rect")]
    assert fills[0] == svg.MODEL
    assert all("color-mix" in f for f in fills[1:])
    assert len(set(fills)) == 4


def test_finish_bar_describes_itself():
    label = parse(svg.finish_bar([0.6, 0.4])).get("aria-label")
    assert "1st 60%" in label and "2nd 40%" in label


def test_finish_bar_survives_an_empty_or_zero_field():
    for probs in ([], [0.0, 0.0]):
        assert parse(svg.finish_bar(probs)) is not None


@pytest.mark.parametrize(
    "n, expected", [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (21, "21st")]
)
def test_ordinals(n, expected):
    assert svg._ordinal(n) == expected


def test_ridgeline_draws_a_curve_and_a_label_per_entrant():
    el = parse(svg.ridgeline([1, 2, 3], [("A", [0, 1, 0]), ("B", [1, 0, 1])]))
    assert len(el.findall(".//polygon")) == 2
    assert len(el.findall(".//polyline")) == 2
    assert {t.text for t in el.findall(".//text[@class='ridge-label']")} == {"A", "B"}


def test_ridgeline_puts_every_row_on_the_same_x_scale():
    """Per-entrant scales would destroy the comparison the chart exists for."""
    el = parse(svg.ridgeline([10, 20, 30], [("A", [0, 1, 0]), ("B", [1, 0, 1])]))
    xs = [
        [p.split(",")[0] for p in line.get("points").split()]
        for line in el.findall(".//polyline")
    ]
    assert xs[0] == xs[1]


def test_ridgeline_survives_degenerate_input():
    assert parse(svg.ridgeline([], [])) is not None
    assert parse(svg.ridgeline([1], [("A", [1])])) is not None
    assert parse(svg.ridgeline([1, 2], [])) is not None


def test_heatmap_prints_the_number_in_every_cell():
    """Colour is reinforcement only — the grid must read in greyscale."""
    el = parse(svg.heatmap([[None, 0.6], [0.4, None]], ["A", "B"]))
    values = [t.text for t in el.findall(".//text[@class='heat-cell']")]
    values += [t.text for t in el.findall(".//text[@class='heat-cell is-strong']")]
    assert sorted(values) == ["40%", "60%"]


def test_heatmap_leaves_the_diagonal_blank():
    el = parse(svg.heatmap([[None, 0.6], [0.4, None]], ["A", "B"]))
    # Two filled cells, two blanks, plus nothing else.
    assert len([r for r in el.findall(".//rect") if r.get("fill") == svg.MODEL]) == 2


def test_heatmap_opacity_tracks_the_value():
    el = parse(svg.heatmap([[None, 1.0], [0.0, None]], ["A", "B"]))
    rects = [r for r in el.findall(".//rect") if r.get("fill") == svg.MODEL]
    opacities = sorted(float(r.get("opacity")) for r in rects)
    assert opacities[0] < opacities[1]


def test_heatmap_degrades_when_the_matrix_does_not_match_the_labels():
    """A shape mismatch draws blanks rather than failing the whole build."""
    el = parse(svg.heatmap([[None, 0.5]], ["A", "B", "C"]))
    assert el is not None
    assert len(_heads(el)) == 6  # 3 rows + 3 cols


def test_heatmap_labels_both_axes():
    el = parse(svg.heatmap([[None, 0.6], [0.4, None]], ["Alice", "Bob"]))
    heads = [t.text for t in _heads(el)]
    # Each name appears twice: once as a column header, once as a row header.
    assert heads.count("Alice") == 2 and heads.count("Bob") == 2
    assert len(heads) == 4


def _heads(el):
    """Row and column name labels, which carry their axis in the class."""
    return el.findall(".//text[@class='heat-head heat-col']") + el.findall(
        ".//text[@class='heat-head heat-row']"
    )


def test_heatmap_says_which_way_round_it_reads():
    """The complaint this answers: a square of names against the same names
    looks symmetrical, is not, and used to carry no caption at all — so every
    cell had two opposite meanings and the reader had to guess which."""
    el = parse(svg.heatmap([[None, 0.6], [0.4, None]], ["Alice", "Bob"]))
    axes = " ".join(t.text for t in el.findall(".//text[@class='heat-axis']"))

    # One sentence, split across the two edges of the grid.
    assert "Each entry" in axes
    assert "finishes above these" in axes
    # And the same thing again for anyone who cannot see the chart at all.
    assert "Each row is one entrant" in el.get("aria-label")


def test_heatmap_cells_carry_the_pair_they_belong_to():
    """So the client can write the hovered cell out as a sentence."""
    el = parse(svg.heatmap([[None, 0.62], [0.38, None]], ["Alice", "Bob"]))
    boxes = el.findall(".//rect[@class='heat-box']")

    assert {(b.get("data-row"), b.get("data-col"), b.get("data-p")) for b in boxes} == {
        ("Alice", "Bob", "62"),
        ("Bob", "Alice", "38"),
    }
    # Indices too, which is what the row-and-column highlight matches on.
    assert {(b.get("data-r"), b.get("data-c")) for b in boxes} == {("0", "1"), ("1", "0")}


def test_heatmap_hover_text_uses_the_full_name_not_the_drawn_one():
    """Column headers are truncated to fit; the readout must not be."""
    el = parse(
        svg.heatmap(
            [[None, 0.6], [0.4, None]],
            ["Shannon", "Bob"],
            ["Shannon (plus Si & Rachel)", "Bob"],
        )
    )
    boxes = el.findall(".//rect[@class='heat-box']")
    rows = {b.get("data-row") for b in boxes}

    assert "Shannon (plus Si & Rachel)" in rows
    # The drawn label stays short, because a full name is three columns wide.
    assert [t.text for t in el.findall(".//text[@class='heat-head heat-col']")] == [
        "Shannon",
        "Bob",
    ]


def test_heatmap_titles_read_as_a_sentence():
    el = parse(svg.heatmap([[None, 0.62], [0.38, None]], ["Alice", "Bob"]))
    titles = [t.text for t in el.findall(".//title")]
    assert "Alice finishes above Bob 62% of the time" in titles


def test_heatmap_full_names_may_run_short_without_failing_the_build():
    """A caller bug should not cost the family their forecast page."""
    el = parse(svg.heatmap([[None, 0.6], [0.4, None]], ["Alice", "Bob"], ["Alice"]))
    boxes = el.findall(".//rect[@class='heat-box']")
    assert {b.get("data-col") for b in boxes} == {"Alice", "Bob"}


def test_heatmap_survives_an_empty_field():
    assert parse(svg.heatmap([], [])) is not None


# -- label fitting ----------------------------------------------------------
def test_fit_labels_leaves_short_names_untouched():
    assert svg.fit_labels(["Alice", "Bob"], 8) == ["Alice", "Bob"]


def test_fit_labels_keeps_the_tail_when_a_cut_would_collide():
    """The real case: two entries whose names differ only at the end.

    Cut at eight, "Zac + Sammy #1" and "Zac + Sammy #2" both become
    "Zac + Sa" — two columns with the same heading, in a chart whose only job
    is telling you which pair a number belongs to.
    """
    out = svg.fit_labels(["Zac + Sammy #1", "Zac + Sammy #2", "Eric"], 8)

    assert len(set(out)) == 3
    assert out[0].endswith("#1")
    assert out[1].endswith("#2")
    assert out[2] == "Eric"
    assert all(len(label) <= 8 for label in out)


def test_fit_labels_does_not_disturb_names_that_were_already_distinct():
    """A long name that clashes with nothing keeps its plain truncation."""
    out = svg.fit_labels(["Shannon (plus Si & Rachel)", "Eric"], 8)
    assert out == ["Shannon ", "Eric"]


def test_fit_labels_gives_up_gracefully_on_genuinely_identical_names():
    """Nothing can distinguish two people entered under the same name."""
    assert svg.fit_labels(["Chris", "Chris"], 8) == ["Chris", "Chris"]


def test_the_heatmap_headings_stay_distinguishable():
    el = parse(
        svg.heatmap(
            [[None, 0.5], [0.5, None]],
            ["Zac + Sammy #1", "Zac + Sammy #2"],
        )
    )
    heads = [t.text for t in el.findall(".//text[@class='heat-head heat-col']")]
    assert len(set(heads)) == 2
