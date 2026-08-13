"""Inline SVG chart primitives, generated at build time.

Every in-table graphic on the leaderboard appears once per entrant, so a chart
library would mean instantiating ~30 canvases on the page everyone opens on
Sunday night. These are plain strings instead: no JavaScript, no library, no
layout shift, and they still render with scripting disabled.

Colours come from CSS custom properties so a single theme change restyles every
chart, and so light and dark mode work without regenerating anything.
"""

from __future__ import annotations

from html import escape
from typing import Sequence

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
) -> str:
    """The signature component: banked, guaranteed, and remaining upside.

    Three segments on one rail, all scaled to a shared maximum so rows are
    directly comparable:

    * solid       — points already banked, which cannot be lost
    * hatched     — guaranteed future points (your own teams must beat each other)
    * outlined    — everything still theoretically reachable

    ``scale_max`` is the largest ceiling in the field, so the longest bar fills
    the rail exactly.
    """
    scale_max = max(scale_max, 1e-9)
    r = height / 2

    def w(value: float) -> float:
        return max(0.0, min(width, width * value / scale_max))

    w_banked = w(banked)
    w_floor = w(banked + guaranteed)
    w_ceiling = w(ceiling)

    label = (
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
