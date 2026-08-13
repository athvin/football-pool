"""The scoring rules.

A bug here is the only failure that would actually embarrass anyone at
Thanksgiving, so every rule and every edge gets its own test.
"""

from __future__ import annotations

import pandas as pd
import pytest
from helpers import mkgames

from football_pool.scoring import (
    entrant_scores,
    money_if_season_ended,
    score_berths,
    score_playoffs,
    score_regular_season,
    score_teams,
)


# -- regular season ---------------------------------------------------------
def test_win_pays_the_leveling_factor(season):
    pts = score_regular_season(season, mkgames([{"home": "ARI", "away": "SEA", "hs": 20, "as_": 17}]))
    assert pts[season.idx["ARI"]] == pytest.approx(2.60)
    assert pts[season.idx["SEA"]] == 0.0


def test_tie_pays_half_to_both_teams(season):
    """A tie is result == 0 — falsy, and the classic way to misread it."""
    pts = score_regular_season(season, mkgames([{"home": "ARI", "away": "SEA", "hs": 20, "as_": 20}]))
    assert pts[season.idx["ARI"]] == pytest.approx(1.30)  # half of 2.60
    assert pts[season.idx["SEA"]] == pytest.approx(0.55)  # half of 1.10


def test_unplayed_games_score_nothing(season):
    pts = score_regular_season(season, mkgames([{"home": "ARI", "away": "SEA"}]))
    assert pts.sum() == 0.0


# -- playoffs ---------------------------------------------------------------
def test_wild_card_upset_pays_flat_with_no_lf(season):
    """Away team in a WC game is always a wild card; beating the host scores +1.0."""
    pts = score_playoffs(season, mkgames([{"home": "KC", "away": "ARI", "hs": 10, "as_": 20, "type": "WC"}]))
    assert pts[season.idx["ARI"]] == pytest.approx(1.0)  # flat, NOT 1.0 + 2.60
    assert pts[season.idx["KC"]] == 0.0


def test_division_winner_winning_its_wild_card_game_scores_nothing(season):
    """The host is the division winner, so a home WC win pays zero."""
    pts = score_playoffs(season, mkgames([{"home": "KC", "away": "ARI", "hs": 30, "as_": 3, "type": "WC"}]))
    assert pts.sum() == 0.0


@pytest.mark.parametrize(
    "gtype, flat", [("DIV", 1.0), ("CON", 1.5), ("SB", 2.0)]
)
def test_later_rounds_add_the_leveling_factor(season, gtype, flat):
    pts = score_playoffs(season, mkgames([{"home": "ARI", "away": "KC", "hs": 20, "as_": 17, "type": gtype}]))
    assert pts[season.idx["ARI"]] == pytest.approx(flat + 2.60)


def test_full_playoff_run_from_a_wild_card(season):
    """WC upset + divisional + conference + Super Bowl, for a 2.60 LF team."""
    games = mkgames(
        [
            {"home": "KC", "away": "ARI", "hs": 10, "as_": 20, "type": "WC"},
            {"home": "ARI", "away": "BUF", "hs": 21, "as_": 14, "type": "DIV"},
            {"home": "ARI", "away": "SF", "hs": 24, "as_": 20, "type": "CON"},
            {"home": "ARI", "away": "NE", "hs": 30, "as_": 27, "type": "SB"},
        ]
    )
    pts = score_playoffs(season, games)
    # 1.0 flat + (1.0+LF) + (1.5+LF) + (2.0+LF) = 5.5 + 3*2.60
    assert pts[season.idx["ARI"]] == pytest.approx(5.5 + 3 * 2.60)


# -- berths -----------------------------------------------------------------
def test_berth_bonuses_are_mutually_exclusive(season):
    pts = score_berths(season, {"KC": 1, "ARI": 4, "SEA": 5, "BUF": 7})
    assert pts[season.idx["KC"]] == 3.0
    assert pts[season.idx["ARI"]] == 3.0  # seed 4 is still a division winner
    assert pts[season.idx["SEA"]] == 1.5
    assert pts[season.idx["BUF"]] == 1.5


def test_no_berth_points_before_the_field_is_settled(season):
    assert score_berths(season, None).sum() == 0.0


def test_per_team_season_maximum(season):
    """A team's ceiling is 20*LF + 7.5: 17 regular-season wins, a division
    title, and three playoff wins after a first-round bye."""
    lf = season.lf_of("ARI")
    reg = score_regular_season(
        season,
        mkgames([{"home": "ARI", "away": "SEA", "hs": 20, "as_": 10, "week": w} for w in range(1, 18)]),
    )[season.idx["ARI"]]
    berth = score_berths(season, {"ARI": 1})[season.idx["ARI"]]
    po = score_playoffs(
        season,
        mkgames(
            [
                {"home": "ARI", "away": "BUF", "hs": 21, "as_": 14, "type": "DIV"},
                {"home": "ARI", "away": "SF", "hs": 24, "as_": 20, "type": "CON"},
                {"home": "ARI", "away": "NE", "hs": 30, "as_": 27, "type": "SB"},
            ]
        ),
    )[season.idx["ARI"]]
    assert reg + berth + po == pytest.approx(20 * lf + 7.5)


# -- aggregation ------------------------------------------------------------
def test_entrant_total_is_the_sum_of_their_teams(season):
    games = mkgames(
        [
            {"home": "KC", "away": "ARI", "hs": 20, "as_": 10},
            {"home": "SEA", "away": "SF", "hs": 20, "as_": 10},
            {"home": "CIN", "away": "DAL", "hs": 20, "as_": 10},  # entrant lacks CIN
        ]
    )
    tp = score_teams(season, games)
    es = entrant_scores(season, tp)
    # Entrant holds KC, SEA, DAL, NE -> KC 2.15 + SEA 1.10
    assert es.loc[0, "total"] == pytest.approx(3.25)
    assert es.loc[0, "rank"] == 1


def test_ties_share_a_rank_and_split_the_money(make_season):
    s = make_season(
        [
            {"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]},
            {"name": "B", "teams": ["KC", "SEA", "DAL", "NE"]},  # identical entry
            {"name": "C", "teams": ["ARI", "BUF", "GB", "MIA"]},
        ]
    )
    games = mkgames([{"home": "KC", "away": "ARI", "hs": 20, "as_": 10}])
    st = entrant_scores(s, score_teams(s, games))
    assert list(st["rank"]) == [1, 1, 3]
    money = money_if_season_ended(s, st)
    # The tied pair split first and second place between them; third is unaffected.
    shared = (0.5 + 0.3) * s.pot / 2
    assert money.iloc[0] == pytest.approx(shared)
    assert money.iloc[1] == pytest.approx(shared)
    assert money.iloc[2] == pytest.approx(0.2 * s.pot)
    assert money.sum() == pytest.approx(s.pot)


def test_a_playoff_tie_scores_nothing_rather_than_guessing(season):
    """Cannot happen under NFL rules, but must never award points by accident."""
    pts = score_playoffs(season, mkgames([{"home": "ARI", "away": "KC", "hs": 20, "as_": 20, "type": "DIV"}]))
    assert pts.sum() == 0.0


def test_seeds_are_attached_when_known(season):
    tp = score_teams(season, mkgames([{"home": "KC", "away": "ARI", "hs": 20, "as_": 10}]), seeds={"KC": 1})
    assert tp.loc["KC", "seed"] == 1
    assert pd.isna(tp.loc["ARI", "seed"])
    assert tp.loc["KC", "berth_points"] == 3.0


def test_no_seed_column_before_the_field_is_settled(season):
    tp = score_teams(season, mkgames([{"home": "KC", "away": "ARI", "hs": 20, "as_": 10}]))
    assert "seed" not in tp.columns


def test_ranks_outside_the_money_pay_nothing(season):
    from football_pool.scoring import payout_for_rank

    assert payout_for_rank(season, 1) == pytest.approx(0.5 * season.pot)
    assert payout_for_rank(season, 4) == 0.0
    assert payout_for_rank(season, 0) == 0.0


def test_fourth_place_collects_nothing(make_season):
    s = make_season(
        [
            {"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]},
            {"name": "B", "teams": ["ARI", "BUF", "GB", "MIA"]},
            {"name": "C", "teams": ["CIN", "WAS", "TEN", "NO"]},
            {"name": "D", "teams": ["NYJ", "CLE", "LV", "CHI"]},
        ]
    )
    games = mkgames(
        [
            {"home": "KC", "away": "PIT", "hs": 20, "as_": 10},
            {"home": "ARI", "away": "PIT", "hs": 20, "as_": 10},
            {"home": "CIN", "away": "PIT", "hs": 20, "as_": 10},
        ]
    )
    st = entrant_scores(s, score_teams(s, games))
    money = money_if_season_ended(s, st)
    assert st.iloc[3]["total"] == 0.0
    assert money.iloc[3] == 0.0
    assert money.sum() == pytest.approx(s.pot)


# -- replay a real season ---------------------------------------------------
def test_replays_the_2025_season(season, games_2025):
    """End-to-end over 285 real games, including a real tie."""
    tp = score_teams(season, games_2025)

    assert tp[["w", "l", "t"]].sum().sum() == 272 * 2  # every REG game, both sides
    assert tp["t"].sum() == 2  # the GB 40-40 DAL tie, one per team

    champ = tp["playoff_points"].idxmax()
    assert champ == "SEA"  # SEA beat NE in the Super Bowl

    # Every team's points must be reachable given its record.
    for team, row in tp.iterrows():
        assert 0 <= row["total"] <= 20 * row["lf"] + 7.5
