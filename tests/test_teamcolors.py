"""Team identity colours, and the contrast maths that keeps the chips readable.

The point of these tests is that a chip must be legible for *every* team, on
both themes, without anyone eyeballing thirty-two of them. The contrast checks
are the load-bearing ones: they are what stops a near-black club colour from
shipping with black text on it.
"""

from __future__ import annotations

import pytest

from football_pool.season import REPO_ROOT, load_season
from football_pool.teamcolors import (
    BLACK,
    TEAM_COLORS,
    WHITE,
    chip_style,
    contrast_ratio,
    readable_text_on,
    relative_luminance,
    rgb,
)

SEASON_YEARS = sorted(
    int(p.name) for p in (REPO_ROOT / "seasons").iterdir() if p.name.isdigit()
)


@pytest.mark.parametrize("year", SEASON_YEARS)
def test_every_team_in_the_season_has_colours(year):
    """A team with no entry renders an unstyled chip, so this must never happen."""
    missing = sorted(set(load_season(year).teams) - set(TEAM_COLORS))
    assert not missing, f"{year}: no colours for {missing}"


def test_there_are_exactly_thirty_two_teams():
    assert len(TEAM_COLORS) == 32


@pytest.mark.parametrize("team", sorted(TEAM_COLORS))
def test_colours_are_well_formed_hex(team):
    primary, secondary = TEAM_COLORS[team]
    for value in (primary, secondary):
        assert value.startswith("#") and len(value) == 7
        r, g, b = rgb(value)
        assert all(0 <= c <= 255 for c in (r, g, b))


@pytest.mark.parametrize("team", sorted(TEAM_COLORS))
def test_every_chip_label_clears_wcag_aa_large(team):
    """The chosen text colour must actually be readable on the club's primary.

    3.0:1 is the AA threshold for large or bold text, which is what a chip is:
    600-weight uppercase mono. Nothing here is allowed to squeak under it.
    """
    primary = TEAM_COLORS[team][0]
    ratio = contrast_ratio(primary, readable_text_on(primary))
    assert ratio >= 3.0, f"{team}: {primary} vs its label is only {ratio:.2f}:1"


@pytest.mark.parametrize("team", sorted(TEAM_COLORS))
def test_the_more_readable_of_black_and_white_is_the_one_chosen(team):
    """Not merely adequate — the better of the two options every time."""
    primary = TEAM_COLORS[team][0]
    chosen = readable_text_on(primary)
    other = WHITE if chosen == BLACK else BLACK
    assert contrast_ratio(primary, chosen) >= contrast_ratio(primary, other)


def test_luminance_endpoints():
    assert relative_luminance("#ffffff") == pytest.approx(1.0)
    assert relative_luminance("#000000") == pytest.approx(0.0)
    # Mid grey is nowhere near 0.5: luminance is not linear in sRGB value.
    assert 0.15 < relative_luminance("#808080") < 0.25


def test_contrast_is_symmetric_and_bounded():
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#123456", "#123456") == pytest.approx(1.0)


def test_light_and_dark_clubs_pick_opposite_labels():
    """Two teams either side of the crossover, pinned so a tweak is deliberate."""
    assert readable_text_on("#ffb612") == BLACK  # Pittsburgh gold
    assert readable_text_on("#0f0f0f") == WHITE  # Las Vegas black
    assert readable_text_on("#fb4f14") == BLACK  # Cincinnati orange
    assert readable_text_on("#241773") == WHITE  # Baltimore purple


def test_rgb_accepts_shorthand_and_rejects_nonsense():
    assert rgb("#abc") == rgb("#aabbcc")
    assert rgb("ffffff") == (255, 255, 255)
    with pytest.raises(ValueError):
        rgb("#12")


def test_chip_style_emits_all_three_custom_properties():
    style = chip_style("KC")
    assert "--team-bg:#e31837" in style
    assert "--team-fg:" in style
    assert "--team-edge:" in style


def test_chip_style_is_case_insensitive():
    assert chip_style("kc") == chip_style("KC")


def test_an_unknown_team_falls_back_silently():
    """A typo must degrade to the neutral chip, not break the build."""
    assert chip_style("ZZZ") == ""


# The theme's surface colours, from site.css. A chip is drawn on one of these.
DARK_SURFACES = ("#070b0e", "#111a21", "#17242d")
LIGHT_SURFACES = ("#f4f1ea", "#fffefb", "#ece7dc")


def _visibility(color: str, surfaces: tuple[str, ...]) -> float:
    """How well a colour separates from the *least* favourable surface."""
    return min(contrast_ratio(color, bg) for bg in surfaces)


@pytest.mark.parametrize("surfaces", [DARK_SURFACES, LIGHT_SURFACES], ids=["dark", "light"])
@pytest.mark.parametrize("team", sorted(TEAM_COLORS))
def test_every_chip_is_visible_on_every_surface(team, surfaces):
    """A chip must never dissolve into the page, on either theme.

    This is the invariant that makes the secondary colour load-bearing rather
    than decorative. Ten clubs have primaries so dark that their fill sits at
    roughly 1.0:1 against the dark theme — Houston's #03202f is 1.05:1, which
    is invisible — so for those the edge is the only thing separating the chip
    from the page. Either channel may carry it; at least one must.
    """
    primary, secondary = TEAM_COLORS[team]
    best = max(_visibility(primary, surfaces), _visibility(secondary, surfaces))
    assert best >= 2.0, (
        f"{team}: neither fill {primary} nor edge {secondary} separates from the "
        f"page (best {best:.2f}:1) — the chip would be an invisible rectangle"
    )
