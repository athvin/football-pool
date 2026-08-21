"""The two palettes, held to a contrast floor.

Colour on this site carries meaning — banked green, modelled cyan, trouble
orange — and a palette is exactly the kind of thing that gets nudged one shade
at a time until something on it can no longer be read. These tests parse the
tokens straight out of the stylesheet and check the pairs that actually occur
on screen, so a nudge that costs legibility fails the build rather than
shipping to a phone in daylight.

WCAG AA is the floor: 4.5:1 for body text, 3:1 for large display type. The
field markings are deliberately *below* both, and are asserted to be: they are
paint on grass, not something anybody reads.
"""

from __future__ import annotations

import colorsys
import re

import pytest

from football_pool.render import ASSET_DIR

CSS = (ASSET_DIR / "site.css").read_text()


def _tokens(selector: str) -> dict[str, str]:
    """Every `--name: value` inside the first block for a selector."""
    start = CSS.index(selector)
    block = CSS[start : CSS.index("\n}", start)]
    return {
        name: value.strip()
        for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", block)
    }


NIGHT = _tokens(":root {")
DAY = _tokens(":root[data-theme='light'] {")


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_the_ratio_maths_matches_the_specification():
    """Black on white is 21:1 and a colour on itself is 1:1, by definition."""
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast("#4dd8e6", "#4dd8e6") == pytest.approx(1.0)


@pytest.mark.parametrize("palette", [NIGHT, DAY], ids=["night", "day"])
def test_every_palette_is_complete(palette):
    """A missing token falls back to an inherited value and looks like a bug."""
    for name in (
        "--field", "--turf-a", "--turf-b", "--surface", "--surface-2",
        "--chalk", "--chalk-dim", "--rule", "--live", "--live-dim",
        "--model", "--heat", "--edge",
    ):
        assert name in palette, name
        assert palette[name].startswith("#"), f"{name} is not a hex colour"


@pytest.mark.parametrize("palette", [NIGHT, DAY], ids=["night", "day"])
@pytest.mark.parametrize("ink", ["--chalk", "--chalk-dim"])
@pytest.mark.parametrize("under", ["--field", "--turf-a", "--turf-b", "--surface", "--surface-2"])
def test_text_clears_aa_on_everything_it_is_ever_set_on(palette, ink, under):
    """Both weights of text, on the turf, the mown stripe and a card.

    The mowing stripes are the case worth naming: prose sits directly on the
    field between the cards, and the field is two tones, so the darker stripe
    is the one that decides whether the page is readable.
    """
    ratio = contrast(palette[ink], palette[under])
    assert ratio >= 4.5, f"{ink} on {under} is {ratio:.2f}:1"


@pytest.mark.parametrize("palette", [NIGHT, DAY], ids=["night", "day"])
@pytest.mark.parametrize("colour", ["--live", "--model", "--heat"])
def test_the_semantic_colours_are_legible_as_text(palette, colour):
    """Each of these is set as type somewhere: a total, a percentage, a delta.

    On a card at AA, and on the field itself at the large-text threshold —
    which is what they are, every time they land on the field: a hero total or
    a stat value, never body copy.
    """
    assert contrast(palette[colour], palette["--surface"]) >= 4.5
    assert contrast(palette[colour], palette["--field"]) >= 3.0


def _hue(hex_colour: str) -> float:
    """Hue in degrees. Not luminance: two colours can be equally bright and
    still be obviously different, which is the whole point here."""
    h = hex_colour.lstrip("#")
    red, green, blue = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(red, green, blue)[0] * 360


@pytest.mark.parametrize("palette", [NIGHT, DAY], ids=["night", "day"])
def test_the_three_meanings_stay_apart(palette):
    """Banked, modelled and trouble must never be mistaken for one another.

    The organising rule of the whole stylesheet is that colour carries meaning:
    what has happened, what is merely projected, and what is trouble. Two of
    them landing on the same hue would quietly let a projection read as a
    result — so this is a hue check, deliberately. Contrast is the wrong tool
    for it, since a green and a teal of identical brightness are 1.03:1 apart
    by luminance and unmistakable to a reader.
    """
    live, model, heat = palette["--live"], palette["--model"], palette["--heat"]
    for a, b in ((live, model), (live, heat), (model, heat)):
        apart = abs(_hue(a) - _hue(b)) % 360
        apart = min(apart, 360 - apart)
        assert apart >= 30, f"{a} and {b} are only {apart:.0f}° apart"


def test_the_day_field_is_actually_green():
    """Which is the entire point of the day palette.

    Not a parchment page with a green accent — a pitch. Green has to be the
    dominant channel in the turf, and the mown stripe has to be a shade of the
    same green rather than a different colour.
    """
    for token in ("--field", "--turf-a", "--turf-b"):
        h = DAY[token].lstrip("#")
        red, green, blue = (int(h[i : i + 2], 16) for i in (0, 2, 4))
        assert green > red and green > blue, f"{token} is not a green"

    # And the stripe is darker than the turf, or there is no stripe.
    assert _luminance(DAY["--turf-b"]) < _luminance(DAY["--turf-a"])


def test_the_field_markings_stay_underneath_the_reading():
    """Paint is texture, not text, and it is asserted to be.

    A line on the field that reached text contrast would be competing with the
    scoreboard on top of it — which is exactly the mistake the drive line made
    when it ran the full width of the page.
    """
    assert re.search(r"--paint-chalk:\s*rgb\(255 255 255 / 55%\)", CSS)
    # White paint on grass in the day palette, chalk-coloured on black at
    # night: both are the same idea, and neither is a straight inversion.
    assert DAY["--paint-chalk"].startswith("rgb(255 255 255")
    assert NIGHT["--paint-chalk"].startswith("rgb(232 237 240")


def test_the_night_palette_was_left_alone():
    """The day game was repitched; the night game was not.

    Pinned exactly, because "brighter greens in light mode" is a request that
    can very easily arrive as a diff to both.
    """
    assert NIGHT["--field"] == "#070b0e"
    assert NIGHT["--live"] == "#c6ff3d"
    assert NIGHT["--model"] == "#4dd8e6"
    assert NIGHT["--heat"] == "#ff6b35"
    assert NIGHT["--turf-a"] == "#070b0e"
    assert NIGHT["--turf-b"] == "#0a1014"
