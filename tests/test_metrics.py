"""Ownership, leverage, and the rest of the fun numbers."""

from __future__ import annotations

import pytest

from football_pool.metrics import (
    leverage,
    ownership,
    pick_report,
    pool_summary,
    rivals,
    team_leaderboard,
)
from football_pool.potential import entrant_outlook
from football_pool.scoring import score_teams
from football_pool.standings import final_seeds


@pytest.fixture
def field(make_season):
    """Deliberate overlap: KC is held twice, BAL three times, and one entry
    has nothing of its own."""
    return make_season(
        [
            {"name": "Ann", "teams": ["KC", "BAL", "DAL", "CIN"]},
            {"name": "Ben", "teams": ["KC", "BAL", "SF", "NE"]},
            {"name": "Cat", "teams": ["BAL", "CIN", "DAL", "SF"]},
        ],
        year=2025,
    )


# -- ownership --------------------------------------------------------------
def test_ownership_counts_every_holder(field):
    held = ownership(field)
    assert held["BAL"].owners == ("Ann", "Ben", "Cat")
    assert held["BAL"].share == pytest.approx(1.0)
    assert held["NE"].owners == ("Ben",)
    assert held["SEA"].owners == ()


def test_unique_and_chalk_flags(field):
    held = ownership(field)
    assert held["NE"].is_unique
    assert not held["KC"].is_unique
    assert held["BAL"].is_chalk  # everyone has it
    assert not held["NE"].is_chalk


def test_every_team_appears_even_if_unowned(field):
    assert len(ownership(field)) == 32


# -- leverage ---------------------------------------------------------------
def test_leverage_counts_only_exclusive_teams(field):
    lev = leverage(field).set_index("name")
    assert set(lev.loc["Ben", "unique_teams"]) == {"SF", "NE"} - {"SF"}  # SF is shared
    assert lev.loc["Ben", "unique_teams"] == ["NE"]
    assert lev.loc["Ben", "leverage"] == pytest.approx(field.lf_of("NE"))


def test_an_entry_with_no_exclusive_team_has_zero_leverage(make_season):
    s = make_season(
        [
            {"name": "Twin A", "teams": ["KC", "BAL", "DAL", "CIN"]},
            {"name": "Twin B", "teams": ["KC", "BAL", "DAL", "CIN"]},
        ],
        year=2025,
    )
    lev = leverage(s).set_index("name")
    assert lev.loc["Twin A", "leverage"] == 0.0
    assert lev.loc["Twin A", "unique_teams"] == []
    assert lev.loc["Twin A", "overlap"] == pytest.approx(1.0)


def test_leverage_is_sorted_best_first(field):
    lev = leverage(field)
    assert list(lev["leverage"]) == sorted(lev["leverage"], reverse=True)


# -- best and worst picks ---------------------------------------------------
def test_pick_report_names_the_carrier_and_the_dead_weight(field, games_2025):
    tp = score_teams(field, games_2025, final_seeds(field, games_2025))
    report = pick_report(field, tp).set_index("name")

    row = report.loc["Ann"]
    points = {t: float(tp.loc[t, "total"]) for t in ("KC", "BAL", "DAL", "CIN")}
    assert row["best_team"] == max(points, key=points.get)
    assert row["worst_team"] == min(points, key=points.get)
    assert 0 <= row["best_share"] <= 1


def test_pick_report_survives_a_scoreless_season(field, games_2025):
    empty = games_2025.copy()
    empty[["played", "home_won", "away_won", "is_tie"]] = False
    report = pick_report(field, score_teams(field, empty))
    assert (report["best_share"] == 0.0).all()


# -- rivals -----------------------------------------------------------------
def test_rivals_chains_the_field_together(field, games_2025):
    tp = score_teams(field, games_2025, final_seeds(field, games_2025))
    outlook = entrant_outlook(field, games_2025, tp, final_seeds(field, games_2025))
    table = rivals(outlook)

    assert table.iloc[0]["gap_to_leader"] == 0.0
    assert table.iloc[0]["chasing"] is None  # nobody ahead of the leader
    assert table.iloc[-1]["chased_by"] is None  # nobody behind last
    assert (table["gap_to_leader"] >= 0).all()


def test_gaps_are_consistent_between_neighbours(field, games_2025):
    tp = score_teams(field, games_2025, final_seeds(field, games_2025))
    outlook = entrant_outlook(field, games_2025, tp, final_seeds(field, games_2025))
    table = rivals(outlook)

    for i in range(len(table) - 1):
        assert table.iloc[i]["chased_gap"] == pytest.approx(table.iloc[i + 1]["chasing_gap"])


# -- summaries --------------------------------------------------------------
def test_team_leaderboard_is_ranked_and_annotated(field, games_2025):
    tp = score_teams(field, games_2025, final_seeds(field, games_2025))
    board = team_leaderboard(field, tp)

    assert list(board["total"]) == sorted(board["total"], reverse=True)
    assert board.loc["BAL", "owners"] == 3
    assert board.loc["SEA", "owners"] == 0


def test_pool_summary_describes_the_field(field, games_2025):
    tp = score_teams(field, games_2025, final_seeds(field, games_2025))
    outlook = entrant_outlook(field, games_2025, tp, final_seeds(field, games_2025))
    summary = pool_summary(field, tp, outlook)

    assert summary["teams_in_play"] == 6  # KC BAL DAL CIN SF NE
    assert summary["most_owned"] == "BAL"
    assert "SEA" in summary["teams_unowned"]
    assert summary["spread"] >= 0
