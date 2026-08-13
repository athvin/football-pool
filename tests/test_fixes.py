"""Regression tests for the bug-fix pass.

One test per fixed behaviour, each written to fail against the pre-fix code.
Grouped by module, referencing the January-window failures the pass was
mostly about: four separate ways the site used to degrade exactly during the
weeks the money gets decided.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from football_pool import cli
from football_pool.nflverse import GameData, parse_games
from football_pool.render import _pool_state, _team_rows, build_context, make_environment
from football_pool.scoring import entrant_scores, score_teams
from football_pool.season import ConfigError, load_season
from football_pool.standings import GameLog, final_seeds
from football_pool import history as history_mod

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def games_2025():
    return parse_games(FIXTURES / "games_2025.csv", 2025)


def _gd(games):
    return GameData(games, 2025, datetime(2026, 1, 20, tzinfo=timezone.utc), None, "cache")


# -- cli: berth bonuses on the terminal leaderboard -------------------------
# -- nflverse: a cancelled game is not staleness ----------------------------
# -- standings: SOV counts victories only -----------------------------------
# -- scoring: neutral-site wild-card guard ----------------------------------
# -- history: mover ordering and zero-point leaders --------------------------
# -- render: the January window ---------------------------------------------
def _ctx(season, games):
    return build_context(season, _gd(games))


# -- season: loud config errors for the money -------------------------------
def _rewrite(season_writer, tmp_path, overrides):
    season_writer(
        tmp_path, 2031,
        [{"name": "Solo", "teams": ["KC", "SEA", "DAL", "NE"]}],
        rules_overrides=overrides, forecast=False,
    )
    return load_season(2031, root=tmp_path)


def test_a_hole_behind_newer_results_is_not_staleness(games_2025):
    """One cancelled game used to make `pool build` refuse to publish from two
    days after the cancellation until the end of the season."""
    cancelled = games_2025.copy()
    reg = cancelled[cancelled["game_type"] == "REG"]
    one = reg.index[40]
    cancelled.loc[one, "played"] = False

    sb = pd.Timestamp(cancelled[cancelled["game_type"] == "SB"]["gameday"].max())
    later = (sb + pd.Timedelta(days=3)).to_pydatetime().replace(tzinfo=timezone.utc)
    gd = GameData(cancelled, 2025, later, None, "network")
    assert gd.days_behind == 0


def test_a_stalled_feed_is_still_caught(games_2025):
    """The frontier rule must not weaken the guard's real job."""
    frozen = games_2025.copy()
    sunday = pd.Timestamp("2025-11-16")
    frozen.loc[pd.to_datetime(frozen["gameday"]) > sunday, "played"] = False
    asof = (sunday + pd.Timedelta(days=5)).to_pydatetime().replace(tzinfo=timezone.utc)
    assert GameData(frozen, 2025, asof, None, "network").days_behind >= 2


def test_phase_is_playoffs_before_the_bracket_rows_exist(season, games_2025):
    """Week 18 done, nflverse yet to publish the bracket: zero unplayed rows
    used to render the headline as 'Final' with the whole postseason left."""
    gap = games_2025[games_2025["game_type"] == "REG"].copy()
    state = _pool_state(_ctx(season, gap), [])
    assert state["phase"] == "Playoffs"


def test_phase_is_final_only_after_a_played_super_bowl(season, games_2025):
    assert _pool_state(_ctx(season, games_2025), [])["phase"] == "Final"


def test_best_of_week_uses_the_scored_week(season, games_2025):
    """January points must not sit under a week-18 headline."""
    mid = games_2025.copy()
    mid.loc[mid["game_type"].isin({"DIV", "CON", "SB"}), "played"] = False
    state = _pool_state(_ctx(season, mid), [])
    assert state["week"] == 18  # max REG week, unchanged
    assert state["scored_week"] == 19  # what the panel must show


def test_reg_games_remaining_is_zero_during_the_playoffs(season, games_2025):
    mid = games_2025.copy()
    mid.loc[mid["game_type"].isin({"DIV", "CON", "SB"}), "played"] = False
    state = _pool_state(_ctx(season, mid), [])
    assert state["reg_games_remaining"] == 0
    assert state["games_remaining"] > 0  # the pair the forecast page branches on


def test_cli_standings_awards_berth_bonuses(monkeypatch, season, games_2025, capsys):
    """The CLI and the site must not disagree in January."""
    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr(
        "football_pool.nflverse.fetch_games", lambda *a, **k: _gd(games_2025)
    )
    assert cli.main(["standings"]) == 0
    out = capsys.readouterr().out

    seeded = entrant_scores(
        season, score_teams(season, games_2025, final_seeds(season, games_2025))
    )
    assert f"{float(seeded['total'].iloc[0]):.2f}" in out
