"""The season simulation.

The load-bearing property is conditioning: games with a final score must be
frozen to what actually happened, so the model is only ever sampling what is
genuinely unknown. Several tests pin that down directly, including the extreme
case where nothing is left to simulate at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from helpers import mkgames

from football_pool.scoring import score_teams
from football_pool.sim import (
    MARKET_ELO_PER_POINT,
    SimConfig,
    build_schedule,
    fit_elo,
    fit_elo_from_market,
    playoff_field,
    simulate,
    win_prob,
)
from football_pool.standings import final_seeds

SIMS = 400  # enough to assert behaviour, small enough to stay fast


@pytest.fixture
def cfg():
    return SimConfig(simulations=SIMS, seed=11)


@pytest.fixture
def preseason(games_2025):
    g = games_2025.copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    return g


@pytest.fixture
def forecast_inputs(season):
    """Flat market expectations: every team at 8.5 wins, no qualitative shift."""
    win_totals = {t: 8.5 for t in season.teams}
    mean = np.zeros(season.n_teams)
    sd = np.full(season.n_teams, 15.0)
    return win_totals, mean, sd


# -- config -----------------------------------------------------------------
def test_config_defaults_when_no_forecast():
    cfg = SimConfig.from_forecast(None)
    assert cfg.simulations == 25_000
    assert cfg.home_field_elo == 48.0


def test_config_reads_the_forecast_file(make_season):
    # sims=None asks for a verbatim copy of the real forecast.yaml — this test
    # is *about* reading the file, so it must see the uncapped 25,000 rather
    # than the small count write_season substitutes for every other test.
    season = make_season(sims=None)
    cfg = SimConfig.from_forecast(season.forecast)
    assert cfg.simulations == 25_000
    assert cfg.seed == 7
    assert cfg.qb_missed_low == 2 and cfg.qb_missed_high == 9


def test_config_tolerates_a_sparse_forecast():
    cfg = SimConfig.from_forecast({"simulations": 100})
    assert cfg.simulations == 100
    assert cfg.elo_scale == 400.0


# -- win probability --------------------------------------------------------
def test_win_probability_is_symmetric_and_monotonic():
    assert win_prob(0.0) == pytest.approx(0.5)
    assert win_prob(100.0) + win_prob(-100.0) == pytest.approx(1.0)
    assert win_prob(200.0) > win_prob(100.0) > win_prob(0.0)


# -- schedule ---------------------------------------------------------------
def test_schedule_covers_every_regular_season_game(season, games_2025):
    s = build_schedule(season, games_2025)
    assert s.n_games == 272
    assert s.team_games.shape == (32, 17)
    assert s.decided.all()
    assert s.games_left == 0


def test_schedule_counts_what_is_left(season, games_2025):
    g = games_2025.copy()
    g.loc[g["week"] > 10, "played"] = False
    s = build_schedule(season, g)
    assert 0 < s.games_left < 272


# -- elo fit ----------------------------------------------------------------
def test_fit_reproduces_the_market_win_totals(season, games_2025, cfg, forecast_inputs):
    """Expected wins under the full noise model must match the targets."""
    win_totals, _, sd = forecast_inputs
    schedule = build_schedule(season, games_2025)
    elo, expected = fit_elo(season, schedule, cfg, win_totals, sd)

    target = np.array([win_totals[t] for t in season.teams])
    assert np.abs(expected - target).max() < 0.05
    assert elo.mean() == pytest.approx(1500.0, abs=1e-6)


def test_stronger_market_expectation_gives_a_higher_rating(season, games_2025, cfg, forecast_inputs):
    _, _, sd = forecast_inputs
    win_totals = {t: 8.5 for t in season.teams}
    win_totals["KC"] = 13.5
    win_totals["ARI"] = 3.5

    schedule = build_schedule(season, games_2025)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    assert elo[season.idx["KC"]] > elo[season.idx["ARI"]]


# -- elo from the betting market --------------------------------------------
@pytest.fixture
def lined(season):
    """A slate of unplayed games carrying a line on every one.

    Each team is paired with the next in the season's own order, so 31 games
    chain all 32 teams together. That connectedness is the whole precondition:
    a spread only ever says how far *apart* two teams are, so a team nobody has
    been compared against has no rating to find.
    """

    def _build(spreads=1.0, **row):
        n = season.n_teams - 1
        values = [spreads] * n if np.isscalar(spreads) else list(spreads)
        return mkgames(
            [
                {
                    "home": season.teams[i],
                    "away": season.teams[i + 1],
                    "spread": values[i],
                    **row,
                }
                for i in range(n)
            ]
        )

    return _build


def test_market_ratings_reproduce_every_posted_line(season, cfg, lined):
    """31 lines against 32 teams is exactly determined, so nothing here is a
    compromise between competing evidence — every equation comes back intact."""
    spreads = [((i % 7) - 3) * 1.5 for i in range(season.n_teams - 1)]

    elo, used = fit_elo_from_market(season, lined(spreads), cfg)

    assert used == season.n_teams - 1
    assert elo.mean() == pytest.approx(1500.0)
    for i, spread in enumerate(spreads):
        gap = elo[season.idx[season.teams[i]]] - elo[season.idx[season.teams[i + 1]]]
        assert gap == pytest.approx(MARKET_ELO_PER_POINT * spread - cfg.home_field_elo)


def test_a_neutral_site_line_carries_no_home_advantage(season, cfg, lined):
    """London, Frankfurt and the Super Bowl: the market's number means something
    different there, and reading it the usual way would rate one side short by
    the whole home-field edge."""
    home, _ = fit_elo_from_market(season, lined(0.0), cfg)
    neutral, _ = fit_elo_from_market(season, lined(0.0, location="Neutral"), cfg)

    # A pick'em on neutral ground says the two teams are level, full stop.
    np.testing.assert_allclose(neutral, 1500.0)
    # The same number at a home venue says the visitor is the better side, by
    # exactly the edge the model would otherwise have handed the hosts.
    gap = home[season.idx[season.teams[0]]] - home[season.idx[season.teams[1]]]
    assert gap == pytest.approx(-cfg.home_field_elo)


def test_only_unplayed_regular_season_lines_are_fitted(season, cfg, lined):
    """A closing line on a game already played records what the market believed
    back then, and the bracket is not what these ratings are for. Neither may
    drag the estimate away from the market's read on the games still ahead."""
    upcoming = lined(2.0)
    history = mkgames(
        [
            {"home": season.teams[0], "away": season.teams[5], "hs": 31, "as_": 3, "spread": 21.0},
            {"home": season.teams[3], "away": season.teams[9], "spread": -17.0, "type": "SB"},
        ]
    )

    baseline, used = fit_elo_from_market(season, upcoming, cfg)
    elo, used_mixed = fit_elo_from_market(
        season, pd.concat([upcoming, history], ignore_index=True), cfg
    )

    assert used_mixed == used == season.n_teams - 1
    np.testing.assert_allclose(elo, baseline)


def test_a_half_measured_league_declines_to_answer(season, cfg):
    """Week 18 alone is the real version of this: 16 games cannot place 32 teams
    on one scale, and inventing the missing comparisons would be worse than
    falling back to the win totals."""
    islands = mkgames(
        [
            {"home": season.teams[i], "away": season.teams[i + 1], "spread": 3.0}
            for i in range(0, season.n_teams - 1, 4)
        ]
    )
    assert fit_elo_from_market(season, islands, cfg) is None


def test_no_posted_lines_means_no_market_fit(season, cfg, lined):
    """Preseason, before the books put anything up."""
    blank = lined(1.0)
    blank["spread_line"] = np.nan
    assert fit_elo_from_market(season, blank, cfg) is None


def test_a_file_without_the_market_columns_is_not_an_error(season, cfg, lined):
    """Snapshots committed before the lines were kept must still project — the
    market is an input to the forecast, never a requirement of the build."""
    games = lined(1.0)
    assert fit_elo_from_market(season, games.drop(columns=["spread_line"]), cfg) is None
    assert fit_elo_from_market(season, games.drop(columns=["location"]), cfg) is None


# -- seeding ----------------------------------------------------------------
def test_seeding_produces_a_valid_field(season):
    rng = np.random.default_rng(0)
    wins = rng.integers(0, 18, size=(50, season.n_teams)).astype(float)
    seeds = playoff_field(season, wins, rng.random((50, season.n_teams)) * 1e-3)

    assert seeds.shape == (50, 2, 7)
    for sim in range(50):
        for ci, conf in enumerate(("AFC", "NFC")):
            teams = [season.teams[i] for i in seeds[sim, ci]]
            assert len(set(teams)) == 7, "no team seeded twice"
            assert all(season.conf_of[t] == conf for t in teams)
            # The top four slots are the four division champions.
            assert len({season.div_of[t] for t in teams[:4]}) == 4


def test_division_winners_outrank_wildcards_on_wins(season):
    """A 4-seed can have fewer wins than a 5-seed; that is the point of the bye."""
    rng = np.random.default_rng(3)
    wins = rng.integers(0, 18, size=(30, season.n_teams)).astype(float)
    seeds = playoff_field(season, wins, rng.random((30, season.n_teams)) * 1e-3)
    for sim in range(30):
        for ci in range(2):
            champs = wins[sim, seeds[sim, ci, :4]]
            assert (np.diff(champs) <= 0).all(), "champions must be ordered by wins"


# -- simulation -------------------------------------------------------------
def test_wins_are_zero_sum(season, preseason, cfg, forecast_inputs):
    win_totals, mean, sd = forecast_inputs
    schedule = build_schedule(season, preseason)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    points, stats, _, _ = simulate(season, schedule, elo, cfg, mean, sd, n=SIMS)

    assert points.shape == (SIMS, 32)
    assert stats["sim_wins"].sum() == pytest.approx(272, abs=0.5)


def test_a_completed_season_simulates_to_its_actual_result(season, games_2025, cfg, forecast_inputs):
    """With every game decided, the model has nothing left to sample.

    Only the playoff bracket is re-run, so the regular-season component must
    reproduce the real scoring exactly.
    """
    win_totals, mean, sd = forecast_inputs
    schedule = build_schedule(season, games_2025)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    points, stats, _, _ = simulate(season, schedule, elo, cfg, mean, sd, n=50)

    actual = score_teams(season, games_2025)
    for team in season.teams:
        # win points are fixed; berth and playoff points still vary.
        expected_wins = actual.loc[team, "w"] + 0.5 * actual.loc[team, "t"]
        assert stats.loc[team, "sim_wins"] == pytest.approx(expected_wins, abs=1e-9)


def test_conditioning_freezes_decided_games(season, games_2025, cfg, forecast_inputs):
    """Half a season played: those wins must be identical in every simulation."""
    win_totals, mean, sd = forecast_inputs
    g = games_2025.copy()
    g.loc[g["week"] > 9, "played"] = False
    g.loc[g["game_type"] != "REG", "played"] = False

    schedule = build_schedule(season, g)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    points, stats, _, _ = simulate(season, schedule, elo, cfg, mean, sd, n=SIMS)

    banked = score_teams(season, g)
    for team in season.teams:
        floor = banked.loc[team, "w"] + 0.5 * banked.loc[team, "t"]
        assert stats.loc[team, "sim_wins"] >= floor - 1e-9
        # Nine weeks remain, so nobody can exceed their banked wins by more.
        assert stats.loc[team, "sim_wins"] <= floor + 9 + 1e-9


def test_a_real_tie_keeps_its_half_win(season, games_2025, cfg, forecast_inputs):
    """The 2025 GB-DAL draw must average half a win to each side."""
    win_totals, mean, sd = forecast_inputs
    schedule = build_schedule(season, games_2025)
    assert schedule.tied.sum() == 1

    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    _, stats, _, _ = simulate(season, schedule, elo, cfg, mean, sd, n=100)

    actual = score_teams(season, games_2025)
    for team in ("GB", "DAL"):
        expected = actual.loc[team, "w"] + 0.5
        assert stats.loc[team, "sim_wins"] == pytest.approx(expected, abs=1e-9)


def test_the_same_seed_reproduces_the_same_season(season, preseason, cfg, forecast_inputs):
    """A day with no games must rebuild byte-identically."""
    win_totals, mean, sd = forecast_inputs
    schedule = build_schedule(season, preseason)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)

    a, _, _, _ = simulate(season, schedule, elo, cfg, mean, sd, n=200)
    b, _, _, _ = simulate(season, schedule, elo, cfg, mean, sd, n=200)
    assert np.array_equal(a, b)


def test_probabilities_are_coherent(season, preseason, cfg, forecast_inputs):
    win_totals, mean, sd = forecast_inputs
    schedule = build_schedule(season, preseason)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    _, stats, _, _ = simulate(season, schedule, elo, cfg, mean, sd, n=SIMS)

    # Exactly eight division winners and six wild cards, every season.
    assert stats["p_division"].sum() == pytest.approx(8.0, abs=0.02)
    assert stats["p_wildcard"].sum() == pytest.approx(6.0, abs=0.02)
    assert stats["p_super_bowl"].sum() == pytest.approx(1.0, abs=0.02)
    assert (stats["p_super_bowl"] <= stats["p_division"] + stats["p_wildcard"] + 1e-9).all()


def test_points_respect_the_per_team_maximum(season, preseason, cfg, forecast_inputs):
    win_totals, mean, sd = forecast_inputs
    schedule = build_schedule(season, preseason)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    points, _, _, _ = simulate(season, schedule, elo, cfg, mean, sd, n=SIMS)

    ceiling = 20 * season.lf + 7.5
    assert (points <= ceiling + 1e-9).all()
    assert (points >= 0).all()


# -- per-game win probability -----------------------------------------------
def test_the_home_win_rate_covers_every_scheduled_game(season, preseason, cfg, forecast_inputs):
    win_totals, mean, sd = forecast_inputs
    schedule = build_schedule(season, preseason)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    _, _, home_rate, _ = simulate(season, schedule, elo, cfg, mean, sd, n=SIMS)

    assert home_rate.shape == (schedule.n_games,)
    assert ((home_rate >= 0.0) & (home_rate <= 1.0)).all()
    # Home field is worth ~48 elo, so the field as a whole must lean home.
    assert home_rate.mean() > 0.5


def test_a_decided_game_is_certain_not_estimated(season, games_2025, cfg, forecast_inputs):
    """Frozen results must read as facts, not as a very confident model.

    This is also what pins the positional join: the rate at index i has to
    describe the same game ``build_schedule`` put at index i, and a real
    season's mix of home wins, away wins and one tie makes that unambiguous.
    """
    win_totals, mean, sd = forecast_inputs
    schedule = build_schedule(season, games_2025)
    elo, _ = fit_elo(season, schedule, cfg, win_totals, sd)
    _, _, home_rate, _ = simulate(season, schedule, elo, cfg, mean, sd, n=50)

    assert set(np.unique(home_rate)) <= {0.0, 0.5, 1.0}
    np.testing.assert_array_equal(home_rate[schedule.home_won], 1.0)
    assert schedule.tied.any()  # 2025 had exactly one
    np.testing.assert_array_equal(home_rate[schedule.tied], 0.5)

    settled_away = schedule.decided & ~schedule.tied & ~schedule.home_won
    np.testing.assert_array_equal(home_rate[settled_away], 0.0)
