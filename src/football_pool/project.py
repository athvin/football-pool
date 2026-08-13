"""Per-entrant projections: where this is likely to finish.

Once picks are locked the field is known, so working out each entrant's chances
is a matrix multiply against the simulated team points — no model of the
opposition required. That is the whole reason this is cheap enough to run on
every build.

Projections are only produced while regular-season games remain. Once the
bracket starts, the simulation would be re-playing games that already happened,
so the site drops the projection panels rather than showing numbers it cannot
stand behind — by then the banked totals and elimination maths tell the story
anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .season import Season
from .sim import SimConfig, Schedule, build_schedule, fit_elo, simulate


@dataclass(frozen=True)
class Projections:
    """Everything the site shows about how the season might end."""

    entrants: pd.DataFrame  # one row per entrant
    teams: pd.DataFrame  # per-team simulated summary
    simulations: int
    games_remaining: int


def _forecast_arrays(season: Season) -> tuple[dict[str, float], np.ndarray, np.ndarray]:
    """Market win totals and the qualitative overlay, as aligned arrays."""
    forecast = season.forecast or {}
    win_totals = forecast.get("win_totals", {})
    qualitative = forecast.get("qualitative_elo", {})

    missing = [t for t in season.teams if t not in win_totals]
    if missing:
        raise ValueError(
            f"forecast.yaml is missing win totals for {missing}. "
            f"Either add them or set `enabled: false` to turn projections off."
        )

    mean = np.array([float(qualitative.get(t, {}).get("mean", 0.0)) for t in season.teams])
    sd = np.array([float(qualitative.get(t, {}).get("sd", 15.0)) for t in season.teams])
    return win_totals, mean, sd


def project(
    season: Season, games: pd.DataFrame, simulations: int | None = None
) -> Projections | None:
    """Simulate the rest of the season and score the real field against it.

    Returns ``None`` when projections would be meaningless or unavailable: no
    forecast configured, or no regular-season games left to simulate.
    """
    if not season.forecast or not season.entrants:
        return None

    schedule = build_schedule(season, games)
    if schedule.games_left == 0:
        return None

    cfg = SimConfig.from_forecast(season.forecast)
    win_totals, qual_mean, qual_sd = _forecast_arrays(season)

    elo, _ = fit_elo(season, schedule, cfg, win_totals, qual_sd)
    points, team_stats = simulate(
        season, schedule, elo, cfg, qual_mean, qual_sd, n=simulations
    )

    return Projections(
        entrants=_score_field(season, points),
        teams=team_stats,
        simulations=points.shape[0],
        games_remaining=schedule.games_left,
    )


def _score_field(season: Season, points: np.ndarray) -> pd.DataFrame:
    """Rank the real entrants inside every simulated season."""
    picks = season.picks_matrix()  # (entrants, teams)
    totals = points @ picks.T  # (simulations, entrants)
    n_sims, n_entrants = totals.shape

    # Competition ranking: your rank is one more than the number of entrants who
    # finished strictly ahead of you, so a tie shares the better rank.
    beaten = (totals[:, None, :] > totals[:, :, None]).sum(axis=2)
    rank = beaten + 1

    payouts = season.payouts
    expected_payout = np.zeros(n_entrants)
    p_by_rank = {}
    for place in range(1, len(payouts) + 1):
        p = (rank == place).mean(axis=0)
        p_by_rank[place] = p
        expected_payout += payouts[place - 1] * p

    return pd.DataFrame(
        {
            "name": [e.name for e in season.entrants],
            "slug": [e.slug for e in season.entrants],
            "p_first": p_by_rank[1],
            "p_cash": sum(p_by_rank.values()),
            "expected_payout": np.round(expected_payout, 2),
            "expected_net": np.round(expected_payout - season.entry_fee, 2),
            "mean_points": np.round(totals.mean(axis=0), 2),
            "p10": np.round(np.percentile(totals, 10, axis=0), 2),
            "p50": np.round(np.percentile(totals, 50, axis=0), 2),
            "p90": np.round(np.percentile(totals, 90, axis=0), 2),
            "mean_rank": np.round(rank.mean(axis=0), 2),
        }
    )


def practically_eliminated(projections: Projections, threshold: float = 0.01) -> set[str]:
    """Entrants the model gives essentially no chance of cashing.

    Mathematical elimination cannot fire until around week 15, which is far too
    late to be interesting. This is the softer badge that can show up in
    November — and being a modelled claim, the site says so.
    """
    df = projections.entrants
    return set(df.loc[df["p_cash"] < threshold, "name"])
