"""Inline SVG chart primitives, generated at build time.

Every in-table graphic on the leaderboard appears once per entrant, so a chart
library would mean instantiating ~30 canvases on the page everyone opens on
Sunday night. These are plain strings instead: no JavaScript, no library, no
layout shift, and they still render with scripting disabled.

Colours come from CSS custom properties so a single theme change restyles every
chart, and so light and dark mode work without regenerating anything.
"""

from __future__ import annotations

import math
import re
from html import escape
from typing import Sequence

from . import teamcolors

# Semantic colour roles. Actual results and model output never share a colour.
BANKED = "var(--live)"
GUARANTEED = "var(--live-dim)"
UPSIDE = "var(--edge)"
MODEL = "var(--model)"
HEAT = "var(--heat)"


def _fmt(value: float) -> str:
    """Trim trailing zeros so the markup stays small and diffs stay readable."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def sparkline(
    values: Sequence[float],
    width: int = 96,
    height: int = 24,
    stroke: str = BANKED,
) -> str:
    """A cumulative-points trend line, sized to sit inside a table cell.

    Flat or empty input degrades to a centred baseline rather than dividing by
    zero, which happens for every entrant in week one.
    """
    if not values:
        return f'<svg class="spark" width="{width}" height="{height}" aria-hidden="true"></svg>'

    lo, hi = min(values), max(values)
    span = hi - lo
    n = len(values)
    pad = 2.0
    usable = height - 2 * pad

    def y(v: float) -> float:
        if span == 0:
            return height / 2
        return pad + usable * (1 - (v - lo) / span)

    step = width / max(n - 1, 1)
    pts = " ".join(f"{i * step:.1f},{y(v):.1f}" for i, v in enumerate(values))
    last_x, last_y = (n - 1) * step, y(values[-1])

    return (
        f'<svg class="spark" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" aria-hidden="true" focusable="false">'
        f'<polyline points="{pts}" fill="none" stroke="{stroke}" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2" fill="{stroke}"/>'
        f"</svg>"
    )


def outlook_bar(
    banked: float,
    guaranteed: float,
    ceiling: float,
    scale_max: float,
    width: int = 220,
    height: int = 14,
    label: str | None = None,
) -> str:
    """The signature component: banked, guaranteed, and remaining upside.

    Three segments on one rail, all scaled to a shared maximum so rows are
    directly comparable:

    * solid       — points already banked, which cannot be lost
    * hatched     — guaranteed future points (your own teams must beat each other)
    * outlined    — everything still theoretically reachable

    ``scale_max`` is the largest ceiling in the field, so the longest bar fills
    the rail exactly.

    ``label`` overrides the description read aloud. The schedule page draws the
    same rail for a single week, where the banked segment is always empty and
    the default wording would open with a meaningless "banked 0".
    """
    scale_max = max(scale_max, 1e-9)
    r = height / 2

    def w(value: float) -> float:
        return max(0.0, min(width, width * value / scale_max))

    w_banked = w(banked)
    w_floor = w(banked + guaranteed)
    w_ceiling = w(ceiling)

    label = label or (
        f"banked {_fmt(banked)}, guaranteed {_fmt(banked + guaranteed)}, "
        f"ceiling {_fmt(ceiling)}"
    )

    return (
        f'<svg class="outlook" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">'
        f'<defs><pattern id="hatch" width="4" height="4" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)">'
        f'<rect width="4" height="4" fill="none"/>'
        f'<line x1="0" y1="0" x2="0" y2="4" stroke="{GUARANTEED}" stroke-width="2"/>'
        f"</pattern></defs>"
        # remaining upside — faint outline out to the ceiling
        f'<rect x="0" y="0" width="{w_ceiling:.1f}" height="{height}" rx="{r}" '
        f'fill="none" stroke="{UPSIDE}" stroke-width="1" opacity="0.55"/>'
        # guaranteed — hatched
        f'<rect x="0" y="0" width="{w_floor:.1f}" height="{height}" rx="{r}" '
        f'fill="url(#hatch)" opacity="0.85"/>'
        # banked — solid
        f'<rect x="0" y="0" width="{w_banked:.1f}" height="{height}" rx="{r}" '
        f'fill="{BANKED}"/>'
        f"</svg>"
    )


def contribution_bar(
    parts: Sequence[tuple[str, float]],
    width: int = 320,
    height: int = 28,
    colors: Sequence[str] | None = None,
) -> str:
    """A stacked bar of how much each of an entrant's teams contributed.

    Segments narrower than a readable label are still drawn; the label is simply
    omitted rather than overflowing into its neighbour.
    """
    total = sum(max(v, 0.0) for _, v in parts)
    if total <= 0:
        return (
            f'<svg class="contrib" width="{width}" height="{height}" aria-hidden="true">'
            f'<rect x="0" y="0" width="{width}" height="{height}" rx="4" '
            f'fill="var(--surface-2)"/></svg>'
        )

    palette = list(colors) if colors else [
        "var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"
    ]
    label = ", ".join(f"{escape(t)} {_fmt(v)}" for t, v in parts)
    out = [
        f'<svg class="contrib" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">'
    ]
    x = 0.0
    for i, (team, value) in enumerate(parts):
        seg = width * max(value, 0.0) / total
        fill = palette[i % len(palette)]
        out.append(
            f'<rect x="{x:.1f}" y="0" width="{max(seg - 1, 0):.1f}" height="{height}" '
            f'rx="3" fill="{fill}"/>'
        )
        if seg > 34:  # only label a segment wide enough to hold the text
            out.append(
                f'<text x="{x + seg / 2:.1f}" y="{height / 2 + 4:.1f}" '
                f'text-anchor="middle" class="contrib-label">{escape(team)}</text>'
            )
        x += seg
    out.append("</svg>")
    return "".join(out)


def range_bar(
    low: float,
    high: float,
    point: float,
    scale_min: float,
    scale_max: float,
    width: int = 200,
    height: int = 16,
) -> str:
    """A projected-score band with a marker for the expected value.

    Drawn in the model colour, never the actual-results colour, so a projection
    is never mistaken for something that already happened.
    """
    span = max(scale_max - scale_min, 1e-9)

    def x(value: float) -> float:
        return max(0.0, min(width, width * (value - scale_min) / span))

    x_lo, x_hi, x_pt = x(low), x(high), x(point)
    mid = height / 2
    label = f"projected {_fmt(low)} to {_fmt(high)}, expected {_fmt(point)}"

    return (
        f'<svg class="range" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">'
        f'<line x1="0" y1="{mid}" x2="{width}" y2="{mid}" stroke="var(--rule)" stroke-width="1"/>'
        f'<rect x="{x_lo:.1f}" y="{mid - 4}" width="{max(x_hi - x_lo, 1):.1f}" height="8" '
        f'rx="4" fill="{MODEL}" opacity="0.35"/>'
        f'<circle cx="{x_pt:.1f}" cy="{mid}" r="3.5" fill="{MODEL}"/>'
        f"</svg>"
    )


def emphasis_lines(
    series: Sequence[tuple[str, Sequence[float]]],
    labels: Sequence[str],
    x_ticks: Sequence[int] | None = None,
    width: int = 900,
    height: int = 360,
    invert: bool = False,
) -> str:
    """Many series in one colour, with only a few labelled.

    Giving thirty entrants thirty colours fails: no set of thirty hues is
    distinguishable, and colouring "the current top few" means people change
    colour week to week, so the chart contradicts itself as the season moves.

    Instead every line is drawn in the same colour at low opacity, and only the
    named ``labels`` are brought forward and labelled at their endpoint. Hovering
    lifts any line, so the quiet ones are still findable.

    ``invert`` flips the axis for rank, where 1 belongs at the top.
    """
    series = [(n, list(v)) for n, v in series if len(v) > 0]
    if not series:
        return (
            f'<svg class="trend" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" aria-hidden="true"></svg>'
        )

    pad_l, pad_r, pad_t, pad_b = 8, 132, 14, 26
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    values = [v for _, vs in series for v in vs]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n_points = max(len(vs) for _, vs in series)
    step = plot_w / max(n_points - 1, 1)

    def y(v: float) -> float:
        frac = (v - lo) / span
        if not invert:
            frac = 1 - frac
        return pad_t + plot_h * frac

    highlighted = set(labels)
    out = [
        f'<svg class="trend" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(str(len(series)))} entrants over {n_points} weeks" '
        f'preserveAspectRatio="xMidYMid meet">'
    ]

    # Week gridlines, kept faint enough to read through.
    for i in range(n_points):
        x = pad_l + i * step
        out.append(
            f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + plot_h}" '
            f'stroke="var(--rule)" stroke-width="0.5" opacity="0.5"/>'
        )
        if x_ticks and i < len(x_ticks):
            out.append(
                f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" '
                f'class="trend-tick">{escape(str(x_ticks[i]))}</text>'
            )

    # Quiet lines first so the emphasised ones sit on top.
    endpoints: list[tuple[str, float, float]] = []
    for emphasised in (False, True):
        for name, vs in series:
            if (name in highlighted) != emphasised:
                continue
            pts = " ".join(
                f"{pad_l + i * step:.1f},{y(v):.1f}" for i, v in enumerate(vs)
            )
            cls = "trend-line is-lead" if emphasised else "trend-line"
            out.append(
                f'<polyline class="{cls}" points="{pts}" fill="none" '
                f'stroke-width="{2.2 if emphasised else 1.4}" '
                f'stroke-linejoin="round" stroke-linecap="round">'
                f"<title>{escape(name)}</title></polyline>"
            )
            if emphasised:
                ex = pad_l + (len(vs) - 1) * step
                ey = y(vs[-1])
                out.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" fill="var(--live)"/>')
                endpoints.append((name, ex, ey))

    # Close finishes put labels on top of each other, so nudge them apart while
    # leaving the marker dots on the true values.
    for name, ex, label_y in _spread(endpoints, minimum_gap=14.0, top=pad_t, bottom=pad_t + plot_h):
        out.append(
            f'<text x="{ex + 8:.1f}" y="{label_y + 4:.1f}" class="trend-label">'
            f"{escape(name[:18])}</text>"
        )

    out.append("</svg>")
    return "".join(out)


def compare_lines(
    series: Sequence[tuple[str, str, Sequence[float]]],
    x_ticks: Sequence[int] | None = None,
    width: int = 900,
    height: int = 340,
    invert: bool = False,
) -> str:
    """Every entrant drawn once, tagged so the viewer can pick who to compare.

    A different question from :func:`emphasis_lines` and so a different chart.
    That one shows the shape of the whole season and is deliberately monochrome.
    This one answers "how am I doing against Paul", where the viewer has named a
    handful of people — and for a small, self-chosen set, distinct colours are
    exactly right. The colours are assigned in the browser in pick order, so the
    first person picked always gets the first colour and nobody's line changes
    hue as the season moves.

    Everything is rendered once, at build time. The interaction is purely a
    class toggle, so the chart is complete and readable with scripting off; it
    simply shows the full field in one colour, which is the honest default.

    ``series`` is ``(display name, slug, values)``. The slug is what the picker
    matches on, so it must be the same slug used in the entrant page URLs.
    """
    series = [(n, s, list(v)) for n, s, v in series if len(v) > 0]
    if not series:
        return (
            f'<svg class="compare" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" aria-hidden="true"></svg>'
        )

    pad_l, pad_r, pad_t, pad_b = 8, 132, 14, 26
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    values = [v for _, _, vs in series for v in vs]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n_points = max(len(vs) for _, _, vs in series)
    step = plot_w / max(n_points - 1, 1)

    def y(v: float) -> float:
        frac = (v - lo) / span
        if not invert:
            frac = 1 - frac
        return pad_t + plot_h * frac

    out = [
        f'<svg class="compare" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(str(len(series)))} entrants over {n_points} weeks, '
        f'select entrants to compare" preserveAspectRatio="xMidYMid meet">'
    ]

    for i in range(n_points):
        x = pad_l + i * step
        out.append(
            f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + plot_h}" '
            f'stroke="var(--rule)" stroke-width="0.5" opacity="0.5"/>'
        )
        if x_ticks and i < len(x_ticks):
            out.append(
                f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" '
                f'class="trend-tick">{escape(str(x_ticks[i]))}</text>'
            )

    for name, slug, vs in series:
        pts = " ".join(f"{pad_l + i * step:.1f},{y(v):.1f}" for i, v in enumerate(vs))
        ex, ey = pad_l + (len(vs) - 1) * step, y(vs[-1])
        tag = f'data-entrant="{escape(slug)}"'
        out.append(
            f'<polyline class="cmp-line" {tag} points="{pts}" fill="none" '
            f'stroke-linejoin="round" stroke-linecap="round">'
            f"<title>{escape(name)}</title></polyline>"
        )
        out.append(f'<circle class="cmp-dot" {tag} cx="{ex:.1f}" cy="{ey:.1f}" r="3.5"/>')
        out.append(
            f'<text class="cmp-label" {tag} x="{ex + 8:.1f}" y="{ey + 4:.1f}" '
            f'data-y="{ey:.1f}">{escape(name[:18])}</text>'
        )

    out.append("</svg>")
    return "".join(out)


def _spread(
    points: Sequence[tuple[str, float, float]],
    minimum_gap: float,
    top: float,
    bottom: float,
) -> list[tuple[str, float, float]]:
    """Push overlapping labels apart, keeping their original order."""
    ordered = sorted(points, key=lambda p: p[2])
    placed: list[tuple[str, float, float]] = []
    previous = -1e9
    for name, x, y_value in ordered:
        y_out = max(y_value, previous + minimum_gap)
        placed.append((name, x, y_out))
        previous = y_out

    # If the stack overflowed the plot, slide the whole run back up.
    if placed and placed[-1][2] > bottom:
        shift = min(placed[-1][2] - bottom, placed[0][2] - top)
        if shift > 0:
            placed = [(n, x, y - shift) for n, x, y in placed]
    return placed


# -- avatars ----------------------------------------------------------------
def _initials(name: str) -> str:
    """The letters an entrant's monogram shows.

    First letters of the first two words, with parenthesised asides dropped
    ("Shannon (plus Si & Rachel)" is Shannon's entry, so it reads S) and a
    trailing entry number kept, because "Zac + Sammy #1" and "#2" are two
    entries and must not wear the same face.
    """
    aside_free = re.sub(r"\(.*?\)", " ", name)
    words = re.findall(r"[A-Za-z]+", aside_free)
    letters = "".join(w[0] for w in words[:2]).upper()
    tail = re.search(r"(\d+)\s*$", name)
    if tail:
        letters += tail.group(1)
    return letters or "?"


def avatar(name: str, teams: Sequence[str] = (), size: int = 44) -> str:
    """A monogram roundel: the pool's stand-in for a profile picture.

    Nobody sends in a headshot for a family pool, and generated fake faces
    would be worse than nothing. So the picture is built from what an entrant
    has actually committed to: the roundel wears their first pick's club
    colours, with their initials on top in whichever of black or white can be
    read on that ground — the same WCAG decision the team chips make.
    Deterministic, so nobody's face changes between builds.

    An entrant with no teams, or a first team we hold no colours for, gets the
    neutral surface in theme variables rather than a broken image.
    """
    initials = _initials(name)
    pair = teamcolors.TEAM_COLORS.get(teams[0].upper()) if teams else None
    if pair:
        ground, edge = pair
        ink = teamcolors.readable_text_on(ground)
    else:
        ground, edge, ink = "var(--surface-2)", "var(--rule)", "var(--chalk)"
    # A third character (a shared entry's number) needs a smaller face to fit.
    font = {1: 21, 2: 18}.get(len(initials), 14)
    return (
        f'<svg class="avatar" width="{size}" height="{size}" viewBox="0 0 48 48" '
        f'aria-hidden="true">'
        f'<circle cx="24" cy="24" r="22.5" fill="{ground}" stroke="{edge}" '
        f'stroke-width="3"/>'
        f'<text x="24" y="24" text-anchor="middle" dominant-baseline="central" '
        f'class="avatar-text" font-size="{font}" fill="{ink}">{escape(initials)}</text>'
        f"</svg>"
    )


def meter(fraction: float, width: int = 60, height: int = 6, fill: str = MODEL) -> str:
    """A slim 0-1 meter for probabilities."""
    f = max(0.0, min(1.0, fraction))
    return (
        f'<svg class="meter" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" aria-hidden="true">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="{height / 2}" '
        f'fill="var(--surface-2)"/>'
        f'<rect x="0" y="0" width="{width * f:.1f}" height="{height}" rx="{height / 2}" '
        f'fill="{fill}"/></svg>'
    )


# -- forecast charts --------------------------------------------------------
def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _place_fill(place: int, places: int) -> str:
    """A sequential ramp from the model colour down to the edge colour.

    Finishing position is ordinal, so it gets a sequential scale rather than
    categorical hues: first place should read as the strong end of one ramp,
    not as an arbitrarily different colour from second.
    """
    if places <= 1 or place <= 1:
        return MODEL
    weight = 100 - int(88 * (place - 1) / (places - 1))
    return f"color-mix(in srgb, {MODEL} {weight}%, {UPSIDE})"


def finish_bar(
    probs: Sequence[float], width: int = 320, height: int = 22, label_min: float = 34.0
) -> str:
    """One entrant's chance of finishing in each place, as a single stacked bar.

    Reads left to right as first place through last. The whole bar is always
    the full width because the probabilities sum to one, so the eye compares
    segment widths between rows without any scaling to think about.
    """
    total = float(sum(probs))
    if not probs or total <= 0:
        return (
            f'<svg class="finish" width="{width}" height="{height}" aria-hidden="true">'
            f'<rect width="{width}" height="{height}" rx="4" fill="var(--surface-2)"/>'
            f"</svg>"
        )

    places = len(probs)
    label = ", ".join(
        f"{_ordinal(i + 1)} {p * 100:.0f}%" for i, p in enumerate(probs) if p >= 0.005
    )
    out = [
        f'<svg class="finish" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">'
    ]

    x = 0.0
    for i, p in enumerate(probs):
        seg = width * max(float(p), 0.0) / total
        out.append(
            f'<rect x="{x:.1f}" y="0" width="{max(seg - 1, 0):.1f}" height="{height}" '
            f'rx="3" fill="{_place_fill(i + 1, places)}">'
            f"<title>{_ordinal(i + 1)}: {p * 100:.1f}%</title></rect>"
        )
        if seg >= label_min:
            out.append(
                f'<text x="{x + seg / 2:.1f}" y="{height / 2 + 3.5:.1f}" '
                f'text-anchor="middle" class="finish-label">{_ordinal(i + 1)}</text>'
            )
        x += seg
    out.append("</svg>")
    return "".join(out)


def ridgeline(
    centers: Sequence[float],
    rows: Sequence[tuple[str, Sequence[float]]],
    width: int = 860,
    row_height: int = 46,
    curve_height: int = 64,
    label_width: int = 150,
) -> str:
    """Every entrant's score distribution on one shared axis.

    Rows deliberately overlap and the fills are translucent, because the
    overlap *is* the message: two curves sitting on top of each other means the
    pool is close, and two that barely touch means it is over. A shared x-scale
    is what makes that readable, so every row is drawn against the same
    ``centers``.
    """
    rows = [(n, list(v)) for n, v in rows if len(v) > 0]
    if not rows or len(centers) < 2:
        return (
            f'<svg class="ridge" width="{width}" height="{row_height}" '
            f'aria-hidden="true"></svg>'
        )

    pad_r, pad_t, pad_b = 12, curve_height - row_height + 8, 26
    plot_w = width - label_width - pad_r
    height = pad_t + row_height * len(rows) + pad_b
    step = plot_w / (len(centers) - 1)

    def x_at(i: int) -> float:
        return label_width + i * step

    out = [
        f'<svg class="ridge" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Simulated final score distribution for '
        f'{escape(str(len(rows)))} entrants" preserveAspectRatio="xMidYMid meet">'
    ]

    # Later rows are drawn over earlier ones, so iterate top-down to keep the
    # stacking order matching the reading order.
    for i, (name, density) in enumerate(rows):
        base = pad_t + row_height * (i + 1)
        points = " ".join(
            f"{x_at(j):.1f},{base - curve_height * min(max(float(v), 0.0), 1.0):.1f}"
            for j, v in enumerate(density)
        )
        area = f"{label_width:.1f},{base:.1f} {points} {x_at(len(density) - 1):.1f},{base:.1f}"
        out.append(
            f'<polygon class="ridge-fill" points="{area}"/>'
            f'<polyline class="ridge-line" points="{points}" fill="none"/>'
            f'<text x="{label_width - 10}" y="{base - 3:.1f}" text-anchor="end" '
            f'class="ridge-label">{escape(name[:20])}</text>'
        )

    # A handful of score ticks along the bottom, not one per bin.
    for i in range(0, len(centers), max(len(centers) // 6, 1)):
        out.append(
            f'<text x="{x_at(i):.1f}" y="{height - 8}" text-anchor="middle" '
            f'class="trend-tick">{centers[i]:.0f}</text>'
        )

    out.append("</svg>")
    return "".join(out)


def fit_labels(labels: Sequence[str], cap: int) -> list[str]:
    """Shorten labels to ``cap`` characters without making two of them equal.

    A column of a head-to-head grid is about eight characters wide, and a plain
    truncation at eight turns "Zac + Sammy #1" and "Zac + Sammy #2" into two
    columns both headed "Zac + Sa" — in a chart whose entire job is telling you
    which pair a number belongs to. Where that happens the tail is kept instead
    of the middle, because the tail is where the thing that tells them apart
    lives. Labels that were already distinct are left exactly as they were, so
    the common case never grows an ellipsis it does not need.
    """
    plain = [label[:cap] for label in labels]
    clashes = {short for short in plain if plain.count(short) > 1}
    return [
        label[: max(cap - 3, 1)] + "…" + label[-2:]
        if short in clashes and len(label) > cap
        else short
        for label, short in zip(labels, plain)
    ]


def heatmap(
    matrix: Sequence[Sequence[float | None]],
    labels: Sequence[str],
    full_labels: Sequence[str] | None = None,
    win_odds: Sequence[float] | None = None,
    verb: str = "finishes above",
    cell: int = 62,
    label_width: int = 132,
    header_height: int = 46,
    axis_width: int = 22,
) -> str:
    """Pairwise probabilities, with the number printed in every cell.

    Colour is reinforcement here, never the only channel — the value is written
    into each cell, so the chart is readable in greyscale, at any level of
    colour vision, and by anyone who simply wants the number.

    ``None`` renders as an empty cell, which is what the diagonal is: nobody
    races themselves.

    The two axes are labelled, and that is not decoration. A grid of names
    against the same names is symmetrical to look at and emphatically not
    symmetrical to read: without a caption saying which way round it goes,
    every cell has two opposite meanings and the reader has to guess. The
    caption is written as one sentence broken across the two axes — "each
    entry" down the side, "finishes above these" along the top — so reading a
    cell is reading the sentence.

    ``full_labels`` carries the untruncated names for the client's hover
    readout; the drawn labels stay short because "Shannon (plus Si & Rachel)"
    is not a column header.

    ``win_odds`` are each entrant's outright odds, as percentages in the same
    order — of winning the pool for the finishing grid, of being paid at all
    for the money one. They ride on the axis labels rather than on the hundred
    cells, and they are what lets the hover readout put a pairwise number next
    to what it actually means for the pool — "beats him 62% of the time" reads
    very differently when both of them win it once in five.

    ``verb`` is the relation a cell asserts, and it is the whole difference
    between the two grids this draws: "finishes above" or "out-earns". It runs
    through the axis caption, every cell's title and the image's own
    description, so the chart cannot end up drawn as one question and read as
    the other.
    """
    n = len(labels)
    if n == 0:
        return '<svg class="heat" width="1" height="1" aria-hidden="true"></svg>'

    names = list(full_labels) if full_labels is not None else list(labels)
    # A short `full_labels` is a caller bug, not a reason to fail a build: fall
    # back to the drawn label for anything missing.
    names += list(labels[len(names):])

    # The drawn labels, cut to what a header can hold but never cut to the
    # point where two of them read the same. See fit_labels.
    cols = fit_labels(labels, 8)
    rows_text = fit_labels(labels, 18)

    grid_left = axis_width + label_width
    # The top caption is centred over the grid, and the grid can be narrower
    # than the caption is long: two entrants are 124px of cells underneath
    # "… finishes above these ↓". Widen the canvas to hold it rather than let
    # the viewBox crop the sentence that says which way the chart reads. The
    # 6.6 is one 9px mono character plus its 0.13em tracking — measured type is
    # not available at build time, and being a few pixels generous here costs
    # nothing but empty field.
    caption = f"… {verb} these ↓"
    caption_right = grid_left + cell * n / 2 + len(caption) * 6.6 / 2
    width = max(grid_left + cell * n, math.ceil(caption_right) + 4)
    height = header_height + cell * n
    out = [
        # The drawn size rides along as a custom property so the stylesheet can
        # refuse to scale the grid up past it. A two-person pool is 278px wide
        # and stretching that across a desktop column draws 62px cells at 250
        # and 10px labels at 40 — see `.heat` in site.css.
        f'<svg class="heat" width="{width}" height="{height}" '
        f'style="--heat-w:{width}px" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="How often each entrant {escape(verb)} each other entrant. '
        f'Each row is one entrant; each column is the rival they are measured '
        f'against." '
        f'preserveAspectRatio="xMidYMid meet">'
    ]

    # The sentence, split across the axes. Down the left, turned to run with
    # the rows it labels; along the top, over the columns it labels.
    out.append(
        f'<text class="heat-axis" transform="translate(11 {header_height + cell * n / 2:.1f}) '
        f'rotate(-90)" text-anchor="middle">Each entry &#8595;</text>'
    )
    # Drawn from the same string that was measured, with the two glyphs the
    # rest of this file writes as entities put back as entities.
    drawn = escape(caption).replace("…", "&#8230;").replace("↓", "&#8595;")
    out.append(
        f'<text class="heat-axis" x="{grid_left + cell * n / 2:.1f}" y="15" '
        f'text-anchor="middle">{drawn}</text>'
    )

    def win_attr(index: int) -> str:
        """This entrant's outright odds, or nothing at all when unknown."""
        if win_odds is None or index >= len(win_odds):
            return ""
        return f' data-win="{float(win_odds[index]):.0f}"'

    for j, col in enumerate(cols):
        out.append(
            f'<text x="{grid_left + cell * j + cell / 2:.1f}" y="{header_height - 9}" '
            f'text-anchor="middle" class="heat-head heat-col" data-c="{j}"'
            f"{win_attr(j)}>{escape(col)}</text>"
        )

    for i, row in enumerate(rows_text):
        y = header_height + cell * i
        out.append(
            f'<text x="{grid_left - 10}" y="{y + cell / 2 + 4:.1f}" text-anchor="end" '
            f'class="heat-head heat-row" data-r="{i}"{win_attr(i)}>{escape(row)}</text>'
        )
        row_values = matrix[i] if i < len(matrix) else ()
        for j in range(n):
            x = grid_left + cell * j
            # How far this cell is from the top-left corner, in cells. The
            # stylesheet holds each one back by that much as the grid arrives,
            # so it deals itself in along the diagonal rather than filling row
            # by row — a hundred cells in reading order is long enough to be a
            # wait, and the same hundred on a wave is one gesture.
            wave = f' style="--i:{i + j}"'
            # A matrix that does not match the labels draws blanks rather than
            # raising: the grid is generated data, and a shape mismatch should
            # show up as a visibly empty cell, not as a failed build.
            value = row_values[j] if j < len(row_values) else None
            if value is None:
                out.append(
                    f'<rect class="heat-blank" x="{x + 1}" y="{y + 1}" '
                    f'width="{cell - 2}" height="{cell - 2}" '
                    f'rx="4" fill="var(--surface-2)" opacity="0.4"{wave}/>'
                )
                continue
            v = float(value)
            out.append(
                f'<rect class="heat-box" x="{x + 1}" y="{y + 1}" '
                f'width="{cell - 2}" height="{cell - 2}" rx="4" '
                f'fill="{MODEL}" opacity="{0.08 + 0.72 * v:.3f}" '
                f'data-r="{i}" data-c="{j}" data-p="{v * 100:.0f}" '
                f'data-row="{escape(names[i], quote=True)}" '
                f'data-col="{escape(names[j], quote=True)}"{wave}>'
                f"<title>{escape(names[i])} {escape(verb)} {escape(names[j])} "
                f"{v * 100:.0f}% of the time</title></rect>"
                f'<text x="{x + cell / 2:.1f}" y="{y + cell / 2 + 4:.1f}" '
                f'text-anchor="middle" class="heat-cell'
                f'{" is-strong" if v >= 0.5 else ""}"{wave}>{v * 100:.0f}%</text>'
            )

    out.append("</svg>")
    return "".join(out)
