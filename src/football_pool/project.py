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
from .sim import (
    SimConfig,
    Schedule,
    build_schedule,
    fit_elo,
    fit_elo_from_market,
    simulate,
)


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
    money_head_to_head: pd.DataFrame  # same pairs, P(row is paid more)
    distribution: Distribution
    home_win_rate: pd.Series  # index=game_id, P(the home side wins)
    # Which market the ratings were fitted to: "market" for this week's posted
    # spreads, "win totals" for the preseason numbers in forecast.yaml. Shown
    # on the forecast page, because the two answer subtly different questions
    # and a reader deserves to know which one produced the number.
    basis: str = "win totals"
    market_games: int = 0  # lines the fit used; 0 on the win-totals path


def _qualitative_arrays(season: Season) -> tuple[np.ndarray, np.ndarray]:
    """The researched deviation from the market, as aligned arrays.

    Needed on both fitting paths: the shift is an opinion about teams, not
    about where the ratings came from.
    """
    qualitative = (season.forecast or {}).get("qualitative_elo", {})
    mean = np.array([float(qualitative.get(t, {}).get("mean", 0.0)) for t in season.teams])
    sd = np.array([float(qualitative.get(t, {}).get("sd", 15.0)) for t in season.teams])
    return mean, sd


def _win_totals(season: Season) -> dict[str, float] | None:
    """Preseason market win totals, or None if the file does not offer any.

    Absent entirely is a legitimate configuration now that the live market can
    supply the ratings on its own — a new season no longer has to start with 32
    numbers typed in by hand. Absent *in part* is still an error, and a loud
    one: that shape is a typo'd team code, and it would otherwise be discovered
    only on the day the market fallback happened to fire.
    """
    win_totals = (season.forecast or {}).get("win_totals") or {}
    if not win_totals:
        return None

    missing = [t for t in season.teams if t not in win_totals]
    if missing:
        raise ValueError(
            f"forecast.yaml has win totals, but not for {missing}. "
            f"Add them, remove the section entirely to fit from the betting "
            f"market alone, or set `enabled: false` to turn projections off."
        )
    return win_totals


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
    qual_mean, qual_sd = _qualitative_arrays(season)

    # The live market first. `fit_elo_from_market` returns None when the posted
    # lines cannot pin all 32 ratings — no lines yet, or only the last week of
    # the season left — and the preseason win totals take over, which is what
    # the projection ran on before there was a choice.
    fitted = fit_elo_from_market(season, games, cfg)
    if fitted is not None:
        elo, market_games = fitted
        basis = "market"
    else:
        win_totals = _win_totals(season)
        if win_totals is None:
            raise ValueError(
                "forecast.yaml has no win totals and the results file has no "
                "usable betting lines, so there is nothing to fit team ratings "
                "to. Add a `win_totals:` section, or set `enabled: false` to "
                "turn projections off."
            )
        elo, _ = fit_elo(season, schedule, cfg, win_totals, qual_sd)
        basis, market_games = "win totals", 0
    points, team_stats, home_win_rate = simulate(
        season, schedule, elo, cfg, qual_mean, qual_sd, n=simulations
    )

    # `build_schedule` filters on exactly this predicate and preserves frame
    # order, so position i of the simulation's arrays is this game. That
    # positional join is the only thing keeping the two in step — if either
    # filter ever changes, change both.
    game_ids = games.loc[games["game_type"] == "REG", "game_id"]

    entrants, finish, h2h, money_h2h, dist = _score_field(season, points)
    return Projections(
        entrants=entrants,
        teams=team_stats,
        simulations=points.shape[0],
        games_remaining=schedule.games_left,
        finish_probs=finish,
        head_to_head=h2h,
        money_head_to_head=money_h2h,
        distribution=dist,
        home_win_rate=pd.Series(home_win_rate, index=game_ids.to_numpy(), name="home_win_rate"),
        basis=basis,
        market_games=market_games,
    )


def _score_field(
    season: Season, points: np.ndarray
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, Distribution]:
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
    return (
        entrants,
        finish,
        _head_to_head(totals, names),
        _money_head_to_head(rank, paid, payouts, names),
        _distribution(totals, names),
    )


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


def _money_head_to_head(
    rank: np.ndarray, paid: int, payouts: np.ndarray, names: list[str]
) -> pd.DataFrame:
    """P(the row's entrant is paid strictly more than the column's).

    The same pairs as :func:`_head_to_head`, priced. What each entrant took
    home in a simulated season is the payout ladder if they finished in a
    paying place and nothing if they did not — the same slice of the same
    ranking the expected-payout column is computed from, so the two can never
    tell different stories.

    Ties are **not** split half-and-half here, which is the one place this
    matrix deliberately parts company with the finishing one. In a pool that
    pays three places, two entrants who both finish out of the money are level
    at nothing, and calling that half a win each would park every mid-table
    pair at 50% and bury the single most interesting fact about them: that
    money almost never separates them at all. So opposite cells add to *less*
    than 100%, and what is missing is exactly the share of seasons that paid
    the two of them the same.
    """
    # Clipped before indexing rather than after: a rank past the last paying
    # place has no rung on the ladder, and `where` evaluates both arms whatever
    # the condition says. The ladder itself is never empty — a pool whose
    # payout_split pays nobody fails to load, so `paid` is at least one.
    place = np.clip(rank - 1, 0, paid - 1)
    took = np.where(rank <= paid, payouts[place], 0.0)
    matrix = (took[:, :, None] > took[:, None, :]).mean(axis=0)
    np.fill_diagonal(matrix, np.nan)
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
