"""The site's vocabulary.

The point of a glossary that is generated rather than written is that it cannot
disagree with the rules it explains. These tests are mostly about that: a
definition naming a number has to name the number the engine is actually using,
and a term the templates reach for has to exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from football_pool import glossary
from football_pool.season import REPO_ROOT

TEMPLATE_DIR = REPO_ROOT / "templates"


def test_every_term_has_a_name_and_a_definition(season):
    terms = glossary.terms(season)
    assert terms

    for key, term in terms.items():
        assert term.term.strip(), key
        # Long enough to be a definition rather than a restatement of the word.
        assert len(term.definition) > 40, key
        assert term.definition.strip().endswith("."), key


def test_definitions_carry_this_season_s_own_numbers(make_season):
    """Not fixed prose: the entry fee and the pot are configurable."""
    season = make_season(
        [
            {"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]},
            {"name": "B", "teams": ["BUF", "SF", "GB", "MIA"]},
        ],
        rules_overrides={"entry_fee": 25, "payout_split": [0.7, 0.3]},
    )
    terms = glossary.terms(season)

    assert "$25" in terms["expected_net"].definition
    assert "$50" in terms["pot"].definition  # two entries at $25
    # Two paying places reads as "first or second", never "the top 2".
    assert "first or second" in terms["p_cash"].definition
    assert "top 2" not in terms["p_cash"].definition


@pytest.mark.parametrize(
    ("split", "expected"),
    [
        ([1.0], "first place"),
        ([0.6, 0.4], "first or second"),
        ([0.5, 0.3, 0.2], "the top 3"),
        ([0.4, 0.3, 0.2, 0.1], "the top 4"),
    ],
)
def test_how_many_places_pay_reads_as_english(make_season, split, expected):
    season = make_season(rules_overrides={"payout_split": split})
    assert expected in glossary.terms(season)["p_cash"].definition


def test_a_one_entry_pool_still_has_a_pot_definition(make_season):
    season = make_season([{"name": "Solo", "teams": ["KC", "SEA", "DAL", "NE"]}])
    assert "$10" in glossary.terms(season)["pot"].definition


def _keys_used_in_templates() -> set[str]:
    """Every glossary key the templates ask for, by reading the templates."""
    used: set[str] = set()
    for path in TEMPLATE_DIR.glob("*.html"):
        text = Path(path).read_text()
        used |= set(re.findall(r"\b(?:info|term)\(\s*'([a-z_]+)'", text))
    return used


def test_every_key_the_templates_reach_for_exists(season):
    """A typo in a template is a build failure, but only on a page nobody hit.

    StrictUndefined turns a missing key into a KeyError at render time, which
    is loud — but only for whichever page happens to use it. This checks the
    whole set at once, so a bad key on the schedule page cannot ship because
    the test suite only rendered the standings.
    """
    known = set(glossary.terms(season))
    missing = _keys_used_in_templates() - known
    assert not missing, f"templates reference unknown glossary keys: {missing}"


def test_the_templates_actually_use_the_glossary():
    """Guards the reverse mistake: the macros quietly falling out of use."""
    used = _keys_used_in_templates()
    assert len(used) >= 10
    # The three the whole complaint was about.
    assert {"on_the_table", "p_first", "expected_payout"} <= used
