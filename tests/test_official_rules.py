"""The rules and leveling factors, pinned season by season.

Two layers, and the split matters:

**Pinned** — for any season we hold the commissioner's published sheet, every
value is asserted exactly. This is the regression test: edit ``rules.yaml``
wrongly and it fails, naming the team and both numbers.

**Structural** — every season directory in the repo is checked against the
prior year's real records, whether or not we hold its sheet. Leveling factors
must rise as records worsen and clubs on the same record must share a factor.
That is what makes a new season safe to add: drop in ``seasons/2027/`` and
these tests cover it automatically, with no edit here.

The one rule the commissioner's sheet does not cover is ties. NFL games can end
level (2025 had one), and the pool's tie policy is a configurable knob rather
than something derived — see ``tie_multiplier`` in ``rules.yaml``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from football_pool.leveling import check_leveling_factors, comparison_table
from football_pool.nflverse import parse_games
from football_pool.season import REPO_ROOT, load_season

FIXTURES = Path(__file__).parent / "fixtures"
OFFICIAL = json.loads((FIXTURES / "official_rules.json").read_text())

# Every season configured in the repo. A new directory enrols itself.
SEASON_YEARS = sorted(
    int(p.name) for p in (REPO_ROOT / "seasons").iterdir() if p.name.isdigit()
)
PINNED_YEARS = sorted(int(y) for y in OFFICIAL if y.isdigit())


def official_factors(year: int) -> dict[str, float]:
    """The full published table for a year, every value read off the sheet."""
    return dict(OFFICIAL[str(year)]["verified"])


def prior_games(year: int):
    """Real results for the season before ``year``, if we have them."""
    path = FIXTURES / f"games_{year - 1}.csv"
    if not path.exists():
        pytest.skip(f"no {year - 1} results fixture to check {year} against")
    return parse_games(path, year - 1)


# -- pinned to the commissioner's sheet -------------------------------------
@pytest.mark.parametrize("year", PINNED_YEARS)
def test_the_configured_table_matches_the_published_sheet(year):
    season = load_season(year)
    expected = official_factors(year)

    assert len(expected) == 32, "the pinned sheet must cover all 32 teams"
    wrong = {
        t: (lf, season.lf_of(t)) for t, lf in expected.items() if season.lf_of(t) != lf
    }
    assert not wrong, "\n".join(
        f"{t}: sheet says {sheet:.2f}, rules.yaml says {mine:.2f}"
        for t, (sheet, mine) in sorted(wrong.items())
    )


@pytest.mark.parametrize("year", PINNED_YEARS)
def test_the_scoring_rules_match_the_published_sheet(year):
    season = load_season(year)
    b = OFFICIAL[str(year)]["bonuses"]

    assert season.entry_fee == OFFICIAL[str(year)]["entry_fee"]
    assert list(season.payout_split) == OFFICIAL[str(year)]["payout_split"]
    assert season.bonuses.division_winner == b["division_winner"]
    assert season.bonuses.wild_card_berth == b["wild_card_berth"]

    for key, flat_attr, lf_attr in (
        ("wild_card_upset", "wild_card_upset_flat", "wild_card_upset_add_lf"),
        ("divisional_win", "divisional_flat", "divisional_add_lf"),
        ("conference_win", "conference_flat", "conference_add_lf"),
        ("super_bowl_win", "super_bowl_flat", "super_bowl_add_lf"),
    ):
        assert getattr(season.bonuses, flat_attr) == b[key]["flat"], key
        assert getattr(season.bonuses, lf_attr) == b[key]["add_lf"], key


def test_the_wild_card_rule_is_the_unusual_one():
    """Worth its own assertion: flat, no leveling factor, and one-way.

    A wild card beating a division winner scores 1.0 with no leveling factor
    added. A division winner winning that same game scores nothing at all.
    """
    season = load_season(2026)
    assert season.bonuses.wild_card_upset_flat == 1.0
    assert season.bonuses.wild_card_upset_add_lf is False
    assert season.bonuses.divisional_add_lf is True  # later rounds do add it


def test_ties_are_a_policy_choice_not_a_published_rule():
    """The sheet is silent on draws, so this stays an explicit, editable knob."""
    season = load_season(2026)
    assert season.tie_multiplier == 0.5
    assert "wild_card_upset" not in OFFICIAL["2026"].get("tie_policy", {})


# -- structural, for every season including future ones ---------------------
@pytest.mark.parametrize("year", SEASON_YEARS)
def test_every_season_is_internally_consistent(year):
    season = load_season(year)
    assert season.n_teams == 32
    assert len(season.divisions) == 8
    assert all(len(ts) == 4 for ts in season.divisions.values())
    assert sum(season.payout_split) == pytest.approx(1.0)
    assert all(lf > 0 for lf in season.lf)


@pytest.mark.parametrize("year", SEASON_YEARS)
def test_leveling_factors_follow_the_prior_season(year):
    """Worse record, higher factor — the whole point of the handicap.

    A deliberate tiebreak between two clubs on the same record is allowed; a
    factor that goes the wrong way down the standings is not.
    """
    season = load_season(year)
    issues = check_leveling_factors(season, prior_games(year))

    backwards = [i for i in issues if i.kind == "not-monotonic"]
    tie_breaks = [i for i in issues if i.kind == "tie-mismatch"]

    # Every non-monotonic flag must be explained by a same-record tiebreak.
    tied_teams = {w for i in tie_breaks for w in i.detail.split()}
    for issue in backwards:
        assert any(t in tied_teams for t in issue.detail.split()), issue.detail


@pytest.mark.parametrize("year", SEASON_YEARS)
def test_the_table_is_reproducible_from_the_prior_standings(year):
    """All but a handful of factors follow mechanically from last season."""
    season = load_season(year)
    table = comparison_table(season, prior_games(year))
    matched = int((table["delta"] == 0).sum())

    assert matched >= 30, (
        f"{year}: only {matched}/32 factors follow from {year - 1} standings\n"
        + table[table["delta"] != 0].to_string()
    )


def test_the_known_2026_tiebreak_is_the_only_deviation():
    """New England and Denver both went 14-3; the sheet separates them.

    New England reached the Super Bowl and Denver did not, which is the most
    likely basis. Pinned so that if the table ever changes, this is reviewed
    rather than silently absorbed.
    """
    season = load_season(2026)
    table = comparison_table(season, prior_games(2026))
    deviations = set(table[table["delta"] != 0].index)

    assert deviations == {"DEN"}
    assert season.lf_of("NE") == 1.10
    assert season.lf_of("DEN") == 1.20
