"""Next-week potential, ceilings, floors, and elimination.

The ceiling must be a true upper bound — never lower than what is actually
achievable — because the "mathematically eliminated" badge is derived from it.
Several tests assert that invariant directly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from football_pool.potential import (
    add_elimination,
    entrant_outlook,
    guaranteed_extra,
    head_to_head_games,
    max_postseason_points,
    next_week_window,
    remaining_win_points,
)
from football_pool.scoring import score_teams
from football_pool.standings import final_seeds, playoff_seeds
from helpers import mkgames


# -- head-to-head: the fact that drives everything --------------------------
def test_your_own_teams_playing_guarantees_points(season):
    """One of them has to win, so the smaller leveling factor is already banked."""
    games = mkgames([{"home": "KC", "away": "SEA"}])  # unplayed, both are picks
    assert guaranteed_extra(season, games, {"KC", "SEA", "DAL", "NE"}) == pytest.approx(1.10)


def test_games_against_outsiders_guarantee_nothing(season):
    games = mkgames([{"home": "KC", "away": "ARI"}])
    assert guaranteed_extra(season, games, {"KC", "SEA", "DAL", "NE"}) == 0.0


def test_played_head_to_head_games_no_longer_count(season):
    games = mkgames([{"home": "KC", "away": "SEA", "hs": 20, "as_": 10}])
    assert head_to_head_games(games, {"KC", "SEA"}).empty
    assert guaranteed_extra(season, games, {"KC", "SEA"}) == 0.0


def test_remaining_points_do_not_double_count_a_civil_war(season):
    """KC (2.15) v SEA (1.10) is worth at most 2.15, not 3.25."""
    games = mkgames([{"home": "KC", "away": "SEA"}])
    assert remaining_win_points(season, games, {"KC", "SEA", "DAL", "NE"}) == pytest.approx(2.15)


# -- next week --------------------------------------------------------------
def test_next_week_uses_the_earliest_unplayed_week(season):
    games = mkgames(
        [
            {"home": "KC", "away": "ARI", "hs": 20, "as_": 10, "week": 1},
            {"home": "KC", "away": "ARI", "week": 2},
            {"home": "SEA", "away": "ARI", "week": 3},
        ]
    )
    best, worst = next_week_window(season, games, {"KC", "SEA", "DAL", "NE"})
    assert best == pytest.approx(2.15)  # only week 2 counts
    assert worst == 0.0


def test_a_bye_scores_nothing(season):
    games = mkgames([{"home": "ARI", "away": "BUF", "week": 5}])
    assert next_week_window(season, games, {"KC", "SEA", "DAL", "NE"}) == (0.0, 0.0)


def test_next_week_civil_war_has_a_floor_and_a_cap(season):
    games = mkgames([{"home": "KC", "away": "SEA", "week": 4}])
    best, worst = next_week_window(season, games, {"KC", "SEA", "DAL", "NE"})
    assert best == pytest.approx(2.15)  # the better LF
    assert worst == pytest.approx(1.10)  # the worse one is still guaranteed


def test_next_week_sums_independent_games(season):
    games = mkgames(
        [
            {"home": "KC", "away": "ARI", "week": 4},
            {"home": "SEA", "away": "BUF", "week": 4},
        ]
    )
    best, worst = next_week_window(season, games, {"KC", "SEA", "DAL", "NE"})
    assert best == pytest.approx(3.25)
    assert worst == 0.0


def test_no_games_left_means_no_next_week(season, games_2025):
    assert next_week_window(season, games_2025, {"KC"}) == (0.0, 0.0)
    assert remaining_win_points(season, games_2025, {"KC"}) == 0.0


# -- postseason ceiling structure -------------------------------------------
def test_single_team_takes_the_division_path(season):
    """7.5 + 3*LF beats the wild-card route by exactly 0.5."""
    lf = season.lf_of("KC")
    assert max_postseason_points(season, {"KC"}) == pytest.approx(7.5 + 3 * lf)


def test_two_teams_in_one_division_cannot_both_win_it(season):
    """KC and DEN share the AFC West, so only one can take the +3.0."""
    got = max_postseason_points(season, {"KC", "DEN"})
    both_as_champions = 2 * 7.5 + 3 * (season.lf_of("KC") + season.lf_of("DEN"))
    assert got < both_as_champions


def test_only_one_team_can_win_the_super_bowl(season):
    """Two champions in different conferences: one lifts the trophy, one does not."""
    kc, phi = season.lf_of("KC"), season.lf_of("PHI")
    got = max_postseason_points(season, {"KC", "PHI"})
    # Best: KC wins it all (7.5 + 3*LF); PHI wins its conference but loses the
    # Super Bowl (3.0 division + divisional + conference = 5.5 + 2*LF).
    best = max(
        (7.5 + 3 * kc) + (5.5 + 2 * phi),
        (7.5 + 3 * phi) + (5.5 + 2 * kc),
    )
    assert got == pytest.approx(best)


def test_only_two_teams_per_conference_win_a_divisional_game(season):
    """Three AFC teams cannot all win in the divisional round."""
    teams = {"KC", "BUF", "BAL"}
    got = max_postseason_points(season, teams)
    all_three_deep = sum(5.5 + 2 * season.lf_of(t) for t in teams)
    assert got < all_three_deep


def test_more_teams_never_lowers_the_ceiling(season):
    """Monotonicity: adding a team cannot reduce the best possible haul."""
    base = max_postseason_points(season, {"KC"})
    assert max_postseason_points(season, {"KC", "PHI"}) >= base
    assert max_postseason_points(season, {"KC", "PHI", "SEA", "NE"}) >= base


def test_four_wild_cards_in_one_conference_is_infeasible(season):
    from football_pool.potential import DEPTH_IN_FIELD, DEPTH_MISSED, _feasible

    afc = ["BAL", "BUF", "HOU", "KC"]
    all_wc = tuple(("WC", DEPTH_IN_FIELD, False) for _ in afc)
    assert not _feasible(season, afc, all_wc)
    assert _feasible(season, afc, all_wc[:3] + ((None, DEPTH_MISSED, False),))


def test_no_teams_scores_nothing(season):
    assert max_postseason_points(season, set()) == 0.0


def test_known_seeds_zero_out_teams_that_missed_the_playoffs(season):
    seeds = {"KC": 1}
    got = max_postseason_points(season, {"KC", "SEA"}, seeds=seeds)
    assert got == pytest.approx(7.5 + 3 * season.lf_of("KC"))


def test_known_seeds_pin_the_berth_type(season):
    """A wild card cannot retroactively collect the division bonus."""
    wc = max_postseason_points(season, {"KC"}, seeds={"KC": 6})
    lf = season.lf_of("KC")
    assert wc == pytest.approx(1.5 + 1.0 + (1 + lf) + (1.5 + lf) + (2 + lf))
    assert wc < max_postseason_points(season, {"KC"}, seeds={"KC": 2})


def test_all_four_teams_missing_the_playoffs(season):
    assert max_postseason_points(season, {"KC", "SEA", "DAL", "NE"}, seeds={}) == 0.0


# -- the assembled outlook --------------------------------------------------
def test_outlook_columns_and_ordering(season, games_2025):
    tp = score_teams(season, games_2025)
    out = entrant_outlook(season, games_2025, tp, final_seeds(season, games_2025))
    assert list(out["rank"]) == sorted(out["rank"])
    for col in ("banked", "floor", "ceiling", "next_week_max", "upside"):
        assert col in out.columns


def test_ceiling_never_falls_below_the_floor(season, games_2025):
    """The invariant the elimination badge depends on, checked mid-season."""
    for cutoff in (0, 1, 5, 10, 14, 17, 18):
        partial = games_2025.copy()
        partial.loc[partial["week"] > cutoff, "played"] = False
        partial.loc[partial["game_type"] != "REG", "played"] = False
        tp = score_teams(season, partial)
        out = entrant_outlook(season, partial, tp, final_seeds(season, partial))
        assert (out["ceiling"] >= out["floor"] - 1e-9).all(), f"violated at week {cutoff}"
        assert (out["floor"] >= out["banked"] - 1e-9).all()


def test_a_finished_season_pins_ceiling_to_the_final_score(season, games_2025):
    """With nothing left to play, ceiling == floor == banked, for everyone."""
    seeds = final_seeds(season, games_2025)
    tp = score_teams(season, games_2025, seeds=seeds)
    out = entrant_outlook(season, games_2025, tp, seeds)

    assert (out["next_week_max"] == 0.0).all()
    assert (out["guaranteed_extra"] == 0.0).all()
    for row in out.itertuples():
        assert row.floor == pytest.approx(row.banked)
        assert row.ceiling == pytest.approx(row.banked), (
            f"{row.name}: a finished season must leave no upside"
        )
        assert row.upside == pytest.approx(0.0)


def test_ceiling_shrinks_as_the_bracket_resolves(make_season, games_2025):
    """Each playoff round eliminates teams, so the ceiling can only fall."""
    s = make_season([{"name": "A", "teams": ["SEA", "NE", "PHI", "LAR"]}])
    seeds = final_seeds(s, games_2025)

    ceilings = []
    for rounds in ([], ["WC"], ["WC", "DIV"], ["WC", "DIV", "CON"], ["WC", "DIV", "CON", "SB"]):
        g = games_2025.copy()
        g.loc[g["game_type"].isin({"WC", "DIV", "CON", "SB"}) & ~g["game_type"].isin(rounds), "played"] = False
        tp = score_teams(s, g, seeds)
        ceilings.append(entrant_outlook(s, g, tp, seeds).iloc[0]["ceiling"])

    assert ceilings == sorted(ceilings, reverse=True), ceilings
    assert ceilings[0] > ceilings[-1]


# -- playoff progress -------------------------------------------------------
def test_progress_is_empty_before_the_field_is_settled(season, games_2025):
    from football_pool.potential import playoff_progress

    assert playoff_progress(season, games_2025, None) == {}


def test_progress_tracks_winners_losers_and_upsets(season, games_2025):
    from football_pool.potential import DEPTH_WON_SUPER_BOWL, playoff_progress

    seeds = final_seeds(season, games_2025)
    prog = playoff_progress(season, games_2025, seeds)

    champ = [t for t, s in prog.items() if s.depth == DEPTH_WON_SUPER_BOWL]
    assert champ == ["SEA"]
    assert not prog["SEA"].eliminated
    # Everyone else in the field lost exactly once.
    assert sum(1 for s in prog.values() if s.eliminated) == 13


def test_progress_ignores_an_impossible_playoff_tie(season):
    from football_pool.potential import DEPTH_IN_FIELD, playoff_progress

    games = mkgames([{"home": "KC", "away": "ARI", "hs": 20, "as_": 20, "type": "DIV"}])
    prog = playoff_progress(season, games, {"KC": 1, "ARI": 5})
    assert prog["KC"].depth == DEPTH_IN_FIELD
    assert not prog["KC"].eliminated and not prog["ARI"].eliminated


def test_a_team_that_missed_the_playoffs_scores_no_postseason_points(season):
    from football_pool.potential import DEPTH_MISSED, _depth_points

    assert _depth_points(season, "KC", None, DEPTH_MISSED, False) == 0.0


def test_preseason_ceiling_is_the_whole_season(make_season, games_2025):
    """Before week 1 the ceiling is every game plus a full playoff run."""
    s = make_season([{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    empty = games_2025.copy()
    empty[["played", "home_won", "away_won", "is_tie"]] = False
    tp = score_teams(s, empty)
    out = entrant_outlook(s, empty, tp, None)
    row = out.iloc[0]
    assert row["banked"] == 0.0
    assert row["ceiling"] > 100  # four teams, seventeen games each, plus playoffs
    assert row["floor"] == pytest.approx(row["guaranteed_extra"])


# -- elimination ------------------------------------------------------------
def test_elimination_fires_only_when_it_is_certain():
    df = pd.DataFrame(
        {
            "name": ["Leader", "Doomed", "Alive"],
            "floor": [90.0, 10.0, 20.0],
            "ceiling": [100.0, 80.0, 95.0],
        }
    )
    out = add_elimination(df)
    assert list(out["eliminated"]) == [False, True, False]


def test_cash_elimination_needs_three_clear_rivals():
    df = pd.DataFrame(
        {
            "name": list("ABCDE"),
            "floor": [90.0, 89.0, 88.0, 87.0, 1.0],
            "ceiling": [95.0, 94.0, 93.0, 92.0, 10.0],
        }
    )
    out = add_elimination(df)
    assert out.loc[4, "eliminated"]
    assert out.loc[4, "cash_eliminated"]
    assert not out.loc[0, "cash_eliminated"]


def test_elimination_on_an_empty_field():
    out = add_elimination(pd.DataFrame({"name": [], "floor": [], "ceiling": []}))
    assert out.empty
    assert "eliminated" in out.columns


def test_nobody_is_eliminated_early_in_a_real_season(season, games_2025):
    """Reproduces the finding that elimination cannot fire until ~week 15."""
    partial = games_2025.copy()
    partial.loc[partial["week"] > 8, "played"] = False
    partial.loc[partial["game_type"] != "REG", "played"] = False
    tp = score_teams(season, partial)
    out = entrant_outlook(season, partial, tp, None)
    assert not out["eliminated"].any()
