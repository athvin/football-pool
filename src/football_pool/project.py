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
class Distribution:
    """Where each entrant's simulated final scores actually landed.

    One shared set of bins across every entrant, deliberately. The interesting
    thing about these curves is how much they overlap — that overlap is the
    difference between "this is close" and "this is over" — and per-entrant
    bins would destroy exactly that comparison.
    """

    centers: np.ndarray  # (bins,) midpoint score of each bin
    density: pd.DataFrame  # index=name, one column per bin, scaled 0-1


@dataclass(frozen=True)
class Projections:
    """Everything the site shows about how the season might end."""

    entrants: pd.DataFrame  # one row per entrant
    teams: pd.DataFrame  # per-team simulated summary
    simulations: int
    games_remaining: int
    # The distributional detail. The simulation already pays for all of this;
    # summarising it down to three percentiles and throwing the rest away was
    # losing the part that makes a forecast worth looking at.
    finish_probs: pd.DataFrame  # index=name, columns 1..n places
    head_to_head: pd.DataFrame  # index/columns=name, P(row finishes above column)
    distribution: Distribution
    home_win_rate: pd.Series  # index=game_id, P(the home side wins)


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
    points, team_stats, home_win_rate = simulate(
        season, schedule, elo, cfg, qual_mean, qual_sd, n=simulations
    )

    # `build_schedule` filters on exactly this predicate and preserves frame
    # order, so position i of the simulation's arrays is this game. That
    # positional join is the only thing keeping the two in step — if either
    # filter ever changes, change both.
    game_ids = games.loc[games["game_type"] == "REG", "game_id"]

    entrants, finish, h2h, dist = _score_field(season, points)
    return Projections(
        entrants=entrants,
        teams=team_stats,
        simulations=points.shape[0],
        games_remaining=schedule.games_left,
        finish_probs=finish,
        head_to_head=h2h,
        distribution=dist,
        home_win_rate=pd.Series(home_win_rate, index=game_ids.to_numpy(), name="home_win_rate"),
    )


def _score_field(
    season: Season, points: np.ndarray
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Distribution]:
    """Rank the real entrants inside every simulated season."""
    names = [e.name for e in season.entrants]
    picks = season.picks_matrix()  # (entrants, teams)
    totals = points @ picks.T  # (simulations, entrants)
    n_entrants = totals.shape[1]

    # Competition ranking: your rank is one more than the number of entrants who
    # finished strictly ahead of you, so a tie shares the better rank.
    beaten = (totals[:, None, :] > totals[:, :, None]).sum(axis=2)
    rank = beaten + 1

    finish = _finish_probs(rank, names, n_entrants)

    # Payout probabilities are a slice of the same table rather than a second
    # pass, so the money and the chart can never tell different stories.
    #
    # Truncated to the places that exist: a two-person pool with three payout
    # tiers can never pay third, and the probability of finishing there is zero
    # rather than undefined. Slicing past the end would otherwise leave the
    # matmul with mismatched shapes.
    place_p = finish.to_numpy()
    paid = min(len(season.payouts), place_p.shape[1])
    payouts = np.asarray(season.payouts[:paid])
    expected_payout = place_p[:, :paid] @ payouts

    entrants = pd.DataFrame(
        {
            "name": names,
            "slug": [e.slug for e in season.entrants],
            "p_first": place_p[:, 0],
            "p_cash": place_p[:, :paid].sum(axis=1),
            "expected_payout": np.round(expected_payout, 2),
            "expected_net": np.round(expected_payout - season.entry_fee, 2),
            "mean_points": np.round(totals.mean(axis=0), 2),
            "p10": np.round(np.percentile(totals, 10, axis=0), 2),
            "p50": np.round(np.percentile(totals, 50, axis=0), 2),
            "p90": np.round(np.percentile(totals, 90, axis=0), 2),
            "mean_rank": np.round(rank.mean(axis=0), 2),
        }
    )
    return entrants, finish, _head_to_head(totals, names), _distribution(totals, names)


def _finish_probs(rank: np.ndarray, names: list[str], n_entrants: int) -> pd.DataFrame:
    """P(finishing in each place), one row per entrant.

    Rows sum to exactly 1.0 — every entrant has exactly one rank in every
    simulated season. Columns do *not*, and must not be asserted to: competition
    ranking means two entrants tied for first leaves nobody in second.
    """
    places = np.arange(1, n_entrants + 1)
    probs = (rank[:, :, None] == places[None, None, :]).mean(axis=0)
    return pd.DataFrame(probs, index=names, columns=places)


def _head_to_head(totals: np.ndarray, names: list[str]) -> pd.DataFrame:
    """P(the row's entrant finishes above the column's).

    A tie counts as half to each side, which is what makes the matrix
    antisymmetric: ``h2h[a][b] + h2h[b][a] == 1`` for every pair. Without that,
    exact ties — two entrants holding the same four teams would tie in every
    single simulation — would quietly vanish from both directions.
    """
    above = (totals[:, :, None] > totals[:, None, :]).mean(axis=0)
    level = (totals[:, :, None] == totals[:, None, :]).mean(axis=0)
    matrix = above + 0.5 * level
    np.fill_diagonal(matrix, np.nan)  # nobody races themselves
    return pd.DataFrame(matrix, index=names, columns=names)


def _distribution(totals: np.ndarray, names: list[str], bins: int = 44) -> Distribution:
    """Smoothed density of each entrant's simulated final score."""
    lo, hi = float(totals.min()), float(totals.max())
    if hi <= lo:  # a dead heat, or a single remaining outcome
        lo, hi = lo - 1.0, hi + 1.0

    edges = np.linspace(lo, hi, bins + 1)
    counts = np.stack([np.histogram(col, bins=edges)[0] for col in totals.T])

    # Scaled against the tallest peak in the whole field, not each entrant's
    # own: a tightly clustered forecast *should* draw taller than a diffuse one,
    # because that difference is the confidence in it.
    peak = counts.max() or 1
    density = counts / peak
    centers = (edges[:-1] + edges[1:]) / 2
    return Distribution(centers=centers, density=pd.DataFrame(density, index=names))


def practically_eliminated(projections: Projections, threshold: float = 0.01) -> set[str]:
    """Entrants the model gives essentially no chance of cashing.

    Mathematical elimination cannot fire until around week 15, which is far too
    late to be interesting. This is the softer badge that can show up in
    November — and being a modelled claim, the site says so.
    """
    df = projections.entrants
    return set(df.loc[df["p_cash"] < threshold, "name"])
