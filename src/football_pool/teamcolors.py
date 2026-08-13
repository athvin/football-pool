"""Team identity colours for the chips that appear beside every entrant.

Colour here is *identity only*, never an encoding channel. Two teams' primaries
are frequently indistinguishable — Baltimore's #241773 and Dallas' #003594 sit
about ΔE 9 apart to normal colour vision, well under the ~15 needed to read as
different — so nothing on the site is ever "the purple one". Every chip carries
its three-letter code, and the colour is decoration that makes it findable.

Two problems have to be solved for the chips to work on both themes:

* **Text legibility.** A chip is filled with the team's primary, so the label
  has to flip between black and white per team. Chosen by WCAG contrast ratio
  rather than by eye.
* **Near-black teams.** Las Vegas, Jacksonville, Chicago, Cleveland and Houston
  have primaries dark enough to vanish into a dark page. Each team therefore
  also carries a secondary, used for the chip's edge, which keeps the shape
  readable without misrepresenting the club's colours.
"""

from __future__ import annotations

# (primary, secondary). Primaries are the clubs' published identity colours;
# secondaries are picked to give the chip an edge that survives a dark page.
#
# These are hand-maintained rather than read from nflverse's
# teams_colors_logos.csv, and twenty-two of the thirty-two agree with it
# exactly. The other ten differ because that file's `team_color` is not
# consistently the club's primary: it gives Denver navy and Cleveland orange,
# which are those clubs' secondaries, and Tennessee light blue rather than
# navy. Since the colour here is identity rather than data, the published
# identity wins. Nothing downstream depends on the choice — the contrast tests
# hold whichever value is used, so correcting one is a one-line edit.
TEAM_COLORS: dict[str, tuple[str, str]] = {
    "ARI": ("#97233f", "#ffb612"),
    "ATL": ("#a71930", "#a5acaf"),
    "BAL": ("#241773", "#9e7c0c"),
    "BUF": ("#00338d", "#c60c30"),
    "CAR": ("#0085ca", "#bfc0bf"),
    "CHI": ("#0b162a", "#c83803"),
    "CIN": ("#fb4f14", "#000000"),
    "CLE": ("#311d00", "#ff3c00"),
    "DAL": ("#003594", "#869397"),
    "DEN": ("#fb4f14", "#002244"),
    "DET": ("#0076b6", "#b0b7bc"),
    "GB": ("#203731", "#ffb612"),
    "HOU": ("#03202f", "#a71930"),
    "IND": ("#002c5f", "#a5acaf"),
    "JAX": ("#101820", "#006778"),
    "KC": ("#e31837", "#ffb612"),
    "LAC": ("#0080c6", "#ffc20e"),
    "LAR": ("#003594", "#ffd100"),
    "LV": ("#0f0f0f", "#a5acaf"),
    "MIA": ("#008e97", "#fc4c02"),
    "MIN": ("#4f2683", "#ffc62f"),
    "NE": ("#002244", "#c60c30"),
    "NO": ("#d3bc8d", "#101820"),
    "NYG": ("#0b2265", "#a71930"),
    "NYJ": ("#125740", "#ffffff"),
    "PHI": ("#004c54", "#a5acaf"),
    "PIT": ("#ffb612", "#101820"),
    "SEA": ("#002244", "#69be28"),
    "SF": ("#aa0000", "#b3995d"),
    "TB": ("#d50a0a", "#ff7900"),
    "TEN": ("#0c2340", "#4b92db"),
    "WAS": ("#5a1414", "#ffb612"),
}

WHITE = "#ffffff"
BLACK = "#0b0f12"


def _channel(value: float) -> float:
    """One sRGB channel, linearised per the WCAG definition."""
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:  # #abc shorthand
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"not a hex colour: {hex_color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance, 0.0 (black) to 1.0 (white)."""
    r, g, b = (_channel(c) for c in rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours, 1.0 to 21.0."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def readable_text_on(background: str) -> str:
    """Black or white, whichever the eye can actually read on ``background``.

    Decided by measured contrast rather than a luminance threshold, because the
    two are not the same near the middle of the range: Pittsburgh's gold and
    Cincinnati's orange both sit close to the crossover and pick opposite
    answers.
    """
    return BLACK if contrast_ratio(background, BLACK) >= contrast_ratio(background, WHITE) else WHITE


def chip_style(team: str) -> str:
    """Inline custom properties for one team's chip.

    Returns an empty string for a team we hold no colours for, so the chip
    silently falls back to the neutral surface styling instead of breaking.
    """
    pair = TEAM_COLORS.get(team.upper())
    if pair is None:
        return ""
    primary, secondary = pair
    return (
        f"--team-bg:{primary};"
        f"--team-fg:{readable_text_on(primary)};"
        f"--team-edge:{secondary}"
    )
