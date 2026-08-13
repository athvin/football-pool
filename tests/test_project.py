"""Per-entrant projections.

These numbers are the most visible thing on the site during preseason, so the
tests focus on internal coherence — probabilities that add up, payouts that
cannot exceed the pot, orderings that follow the underlying teams — and on the
cases where the module must decline to answer.
"""

from __future__ import annotations

import numpy as np
import pytest

from football_pool.project import practically_eliminated, project

SIMS = 600


@pytest.fixture
def preseason(games_2025):
    g = games_2025.copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    return g


@pytest.fixture
def field(make_season):
    """A spread of entries: strong, middling, and deliberately weak."""
    return make_season(
        [
            {"name": "Strong", "teams": ["KC", "BAL", "DAL", "CIN"]},
            {"name": "Middle", "teams": ["DET", "BUF", "TB", "CHI"]},
            {"name": "Weak", "teams": ["NE", "SF", "SEA", "LAR"]},
        ],
        year=2026,
    )


# -- when projections are withheld ------------------------------------------
def test_no_projection_without_a_forecast(make_season, preseason, tmp_path):
    """forecast.yaml is optional; the rest of the site must not depend on it."""
    s = make_season([{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    object.__setattr__(s, "forecast", None)
    assert project(s, preseason) is None


def test_no_projection_once_the_regular_season_is_done(field, games_2025):
    """Re-simulating a finished bracket would invent results, so it declines."""
    assert project(field, games_2025) is None


def test_no_projection_without_entrants(make_season, preseason):
    s = make_season([{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    object.__setattr__(s, "entrants", ())
    assert project(s, preseason) is None


def test_incomplete_win_totals_are_reported_clearly(make_season, preseason):
    s = make_season([{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    forecast = dict(s.forecast)
    forecast["win_totals"] = {"KC": 10.5}
    object.__setattr__(s, "forecast", forecast)

    with pytest.raises(ValueError, match="missing win totals"):
        project(s, preseason)


# -- coherence --------------------------------------------------------------
def test_probabilities_sum_across_the_field(field, preseason):
    p = project(field, preseason, simulations=SIMS)
    df = p.entrants

    assert len(df) == 3
    # Exactly one entrant wins each simulated season.
    assert df["p_first"].sum() == pytest.approx(1.0, abs=0.02)
    # With three entrants and three paid places, everybody always cashes.
    assert df["p_cash"].sum() == pytest.approx(3.0, abs=0.02)
    assert ((df["p_first"] >= 0) & (df["p_first"] <= 1)).all()


def test_expected_payouts_distribute_the_whole_pot(field, preseason):
    p = project(field, preseason, simulations=SIMS)
    assert p.entrants["expected_payout"].sum() == pytest.approx(field.pot, abs=0.5)
    net = p.entrants["expected_payout"] - field.entry_fee
    assert np.allclose(p.entrants["expected_net"], net, atol=0.01)


def test_percentile_band_is_ordered(field, preseason):
    df = project(field, preseason, simulations=SIMS).entrants
    assert (df["p10"] <= df["p50"]).all()
    assert (df["p50"] <= df["p90"]).all()
    assert ((df["mean_points"] >= df["p10"]) & (df["mean_points"] <= df["p90"])).all()


def test_a_stronger_entry_projects_better(field, preseason):
    df = project(field, preseason, simulations=SIMS).entrants.set_index("name")
    assert df.loc["Strong", "p_first"] > df.loc["Weak", "p_first"]
    assert df.loc["Strong", "mean_points"] > df.loc["Weak", "mean_points"]
    assert df.loc["Strong", "mean_rank"] < df.loc["Weak", "mean_rank"]


def test_identical_entries_project_identically(make_season, preseason):
    """Two people holding the same four teams must get the same odds."""
    s = make_season(
        [
            {"name": "Twin A", "teams": ["KC", "BAL", "DAL", "CIN"]},
            {"name": "Twin B", "teams": ["KC", "BAL", "DAL", "CIN"]},
            {"name": "Other", "teams": ["NE", "SF", "SEA", "LAR"]},
        ],
        year=2026,
    )
    df = project(s, preseason, simulations=SIMS).entrants.set_index("name")
    assert df.loc["Twin A", "mean_points"] == pytest.approx(df.loc["Twin B", "mean_points"])
    assert df.loc["Twin A", "p_first"] == pytest.approx(df.loc["Twin B", "p_first"])


def test_metadata_reports_what_was_simulated(field, preseason):
    p = project(field, preseason, simulations=SIMS)
    assert p.simulations == SIMS
    assert p.games_remaining == 272
    assert len(p.teams) == 32


def test_projection_is_deterministic(field, preseason):
    a = project(field, preseason, simulations=SIMS).entrants
    b = project(field, preseason, simulations=SIMS).entrants
    assert np.allclose(a["p_first"], b["p_first"])
    assert np.allclose(a["mean_points"], b["mean_points"])


# -- conditioning shows up in the projections -------------------------------
def test_a_hot_start_improves_the_projection(make_season, games_2025):
    """Banked points must carry through into the forecast."""
    s = make_season(
        [
            {"name": "Hot", "teams": ["KC", "BAL", "DAL", "CIN"]},
            {"name": "Cold", "teams": ["NE", "SF", "SEA", "LAR"]},
        ],
        year=2026,
    )

    early = games_2025.copy()
    early.loc[early["week"] > 4, "played"] = False
    early.loc[early["game_type"] != "REG", "played"] = False

    # Force every one of Hot's teams to win their first four, and Cold's to lose.
    hot, cold = {"KC", "BAL", "DAL", "CIN"}, {"NE", "SF", "SEA", "LAR"}
    played = early["played"]
    for idx in early[played].index:
        h, a = early.at[idx, "home_team"], early.at[idx, "away_team"]
        if h in hot or a in cold:
            early.at[idx, "home_won"], early.at[idx, "away_won"] = True, False
        elif a in hot or h in cold:
            early.at[idx, "home_won"], early.at[idx, "away_won"] = False, True
    early["is_tie"] = False

    df = project(s, early, simulations=SIMS).entrants.set_index("name")
    assert df.loc["Hot", "p_first"] > 0.9
    assert df.loc["Hot", "p10"] > df.loc["Cold", "p90"]


def test_fewer_games_left_narrows_the_band(field, games_2025, preseason):
    """Uncertainty must shrink as the season is played out."""
    late = games_2025.copy()
    late.loc[late["week"] > 15, "played"] = False
    late.loc[late["game_type"] != "REG", "played"] = False

    wide = project(field, preseason, simulations=SIMS).entrants
    narrow = project(field, late, simulations=SIMS).entrants

    wide_span = (wide["p90"] - wide["p10"]).mean()
    narrow_span = (narrow["p90"] - narrow["p10"]).mean()
    assert narrow_span < wide_span


# -- the soft elimination badge ---------------------------------------------
def test_practically_eliminated_flags_hopeless_entries(field, preseason):
    p = project(field, preseason, simulations=SIMS)
    # Everyone cashes in a three-person, three-payout pool.
    assert practically_eliminated(p) == set()
    # With an impossible threshold, everyone qualifies.
    assert practically_eliminated(p, threshold=1.1) == {"Strong", "Middle", "Weak"}
