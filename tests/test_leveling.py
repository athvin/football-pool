"""Deriving and checking leveling factors from the prior season.

The commissioner owns these numbers. These tests pin down the structure well
enough to catch a typo, without pretending the exact values are computable.
"""

from __future__ import annotations

import pytest

from football_pool.leveling import (
    check_leveling_factors,
    comparison_table,
    conference_ranking,
    prior_season_wins,
    propose_leveling_factors,
)


@pytest.fixture
def wins(season, games_2025):
    return prior_season_wins(season, games_2025)


# -- prior records ----------------------------------------------------------
def test_prior_wins_count_a_tie_as_half(season, games_2025, wins):
    assert wins["DAL"] == 7.5  # the 40-40 draw with Green Bay
    assert wins["GB"] == 9.5
    assert sum(wins.values()) == pytest.approx(272)


def test_ranking_is_best_first_and_stable(season, wins):
    afc = conference_ranking(season, wins, "AFC")
    assert len(afc) == 16
    assert wins[afc[0]] >= wins[afc[-1]]
    assert afc == conference_ranking(season, wins, "AFC")  # deterministic


# -- the real 2026 table ----------------------------------------------------
def test_the_configured_table_matches_the_structure(season, games_2025):
    """31 of 32 factors follow from 2025 records; only NE/DEN is a tiebreak."""
    table = comparison_table(season, games_2025)
    mismatched = table[table["delta"] != 0]

    assert len(table) == 32
    assert set(mismatched.index) == {"DEN"}


def test_only_the_known_tiebreak_is_flagged(season, games_2025):
    issues = check_leveling_factors(season, games_2025)
    assert {i.kind for i in issues} == {"not-monotonic", "tie-mismatch"}
    assert all("14.0" in i.detail or "DEN" in i.detail or "NE" in i.detail for i in issues)


def test_factors_rise_as_records_worsen(season, games_2025, wins):
    """The whole point of the handicap: a worse team pays more per win."""
    table = comparison_table(season, games_2025)
    for conf in ("AFC", "NFC"):
        rows = table[table["conference"] == conf].sort_values("rank")
        proposed = list(rows["proposed"])
        assert proposed == sorted(proposed), f"{conf} proposal is not monotonic"


# -- proposing a new year ---------------------------------------------------
def test_equal_records_get_equal_factors(season, games_2025, wins):
    proposed = propose_leveling_factors(season, games_2025)
    for conf in ("AFC", "NFC"):
        by_record: dict[float, set[float]] = {}
        for t in season.conference_teams(conf):
            by_record.setdefault(wins[t], set()).add(proposed[t])
        for record, factors in by_record.items():
            assert len(factors) == 1, f"{conf} {record} wins got {factors}"


def test_the_proposal_draws_from_the_existing_ladder(season, games_2025):
    """Every proposed value comes from the ladder, and the order is preserved.

    Not a straight permutation: tied clubs share one value, so the rungs below
    them go unused. That is exactly what the real table does — LV, NYJ and TEN
    all finished 3-14 and all sit at 2.50, using one rung between them.
    """
    proposed = propose_leveling_factors(season, games_2025)
    for conf in ("AFC", "NFC"):
        teams = season.conference_teams(conf)
        ladder = set(season.lf_of(t) for t in teams)
        assert {proposed[t] for t in teams} <= ladder
        assert min(proposed[t] for t in teams) == min(ladder)


def test_tied_clubs_consume_one_rung_between_them(season, games_2025, wins):
    """Three clubs on the same record take one value, not three."""
    proposed = propose_leveling_factors(season, games_2025)
    bottom = [t for t in season.conference_teams("AFC") if wins[t] == 3.0]
    assert len(bottom) == 3
    assert len({proposed[t] for t in bottom}) == 1


def test_a_custom_ladder_is_honoured(season, games_2025, wins):
    ladder = {
        "AFC": [round(1.0 + 0.1 * i, 2) for i in range(16)],
        "NFC": [round(1.0 + 0.1 * i, 2) for i in range(16)],
    }
    proposed = propose_leveling_factors(season, games_2025, ladder=ladder)
    best = conference_ranking(season, wins, "AFC")[0]
    assert proposed[best] == 1.0
    assert max(proposed.values()) <= 2.5


def test_a_wrong_sized_ladder_is_rejected(season, games_2025):
    with pytest.raises(ValueError, match="need 16 leveling factors"):
        propose_leveling_factors(season, games_2025, ladder={"AFC": [1.0], "NFC": [1.0]})


# -- catching a real mistake ------------------------------------------------
def test_a_transposed_pair_is_caught(make_season, games_2025):
    """The realistic error: two rows swapped while copying the sheet."""
    swapped = make_season(
        [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}],
        rules_overrides={"leveling_factors": {"SEA": 2.60, "ARI": 1.10}},
    )
    issues = check_leveling_factors(swapped, games_2025)
    details = " ".join(i.detail for i in issues)
    assert "SEA" in details or "ARI" in details
    assert any(i.kind == "not-monotonic" for i in issues)


def test_a_clean_table_reports_nothing(make_season, games_2025):
    """A table generated straight from the structure must raise no flags."""
    base = make_season([{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    clean = propose_leveling_factors(base, games_2025)
    fixed = make_season(
        [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}],
        rules_overrides={"leveling_factors": clean},
    )
    assert check_leveling_factors(fixed, games_2025) == []
