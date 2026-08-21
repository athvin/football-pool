"""The January bracket, from whatever the standings currently say.

A fourteen-team bracket is a fixed shape — three wild-card games a conference,
two divisional, one championship, one Super Bowl — and the only thing that
changes between August and February is how much of it is known. This module
builds the shape once and fills in as much as it can:

* **Before the first kickoff** nothing is known, and the shape is drawn empty.
  :func:`standings.playoff_seeds` deliberately returns nothing until a game has
  been played, because with every club 0-0 the tiebreaker ladder falls through
  to its alphabetical fallback and produces a confident-looking field in which
  Arizona is a one seed. An empty bracket is honest; that one is not.
* **In season** the seeds are a projection, so the wild-card round is drawn
  from them — 2 v 7, 3 v 6, 4 v 5, with the one seed on a bye — and everything
  past it is drawn as slots, because reseeding means the divisional pairings
  genuinely are not knowable until the wild-card round is over.
* **In January** the real games arrive in the results feed and replace the
  slots one round at a time, with their scores.

Nothing here knows about pools, entrants or points. What a bracket game is
worth is the schedule module's question, and it is asked separately by the
renderer — which is what keeps this file about football.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Sequence

import pandas as pd

from .season import Season

# The rounds, in order, with how many games each conference plays and what the
# page calls them. The Super Bowl is the one round with no conference.
ROUNDS: tuple[tuple[str, str, int], ...] = (
    ("WC", "Wild Card", 3),
    ("DIV", "Divisional", 2),
    ("CON", "Conference", 1),
    ("SB", "Super Bowl", 1),
)

# Who plays whom in the wild-card round, by seed. The one seed is not here on
# purpose: it is on a bye, which is worth saying out loud rather than leaving
# as an absence.
WILD_CARD_PAIRS: tuple[tuple[int, int], ...] = ((2, 7), (3, 6), (4, 5))

CONFERENCES: tuple[str, str] = ("AFC", "NFC")


@dataclass(frozen=True)
class Side:
    """One side of a bracket game.

    ``team`` is None until it is known. ``label`` says what the slot is in the
    meantime — "3 seed" while the seeds are a projection, "Wild Card winner"
    where reseeding means nobody can say yet.
    """

    team: str | None
    seed: int | None
    label: str
    score: int | None = None
    won: bool = False


@dataclass(frozen=True)
class Tie:
    """One game in the bracket, known or not."""

    round: str
    round_label: str
    conference: str
    home: Side
    away: Side
    played: bool = False
    game_id: str | None = None

    @property
    def known(self) -> bool:
        """Both sides settled — a real matchup rather than a pair of slots."""
        return self.home.team is not None and self.away.team is not None


def _by_seed(seeds: dict[str, int], conference: str, season: Season) -> dict[int, str]:
    """This conference's seeded teams, keyed by seed."""
    return {
        seed: team
        for team, seed in seeds.items()
        if season.conf_of.get(team) == conference
    }


def _played_games(games: pd.DataFrame, round_code: str) -> list[Any]:
    """The real games of one round, in the order they kick off."""
    if games.empty:
        return []
    slate = games[games["game_type"] == round_code]
    if slate.empty:
        return []
    return list(slate.sort_values(["gameday", "game_id"]).itertuples())


def _side_from(row: Any, team: str, seeds: dict[str, int], *, is_home: bool) -> Side:
    """A side of a real game, with its score and whether it won.

    Both are gated on the game having been played rather than on the score
    column being populated. A feed that carries a scheduled matchup with stale
    numbers beside it — which is exactly what a fixture built by blanking the
    `played` flags looks like — must not have those numbers rendered as a
    result on a bracket.
    """
    played = bool(row.played)
    score = row.home_score if is_home else row.away_score
    seed = seeds.get(team)
    return Side(
        team=team,
        seed=seed,
        label=f"{seed} seed" if seed else team,
        score=None if not played or pd.isna(score) else int(score),
        won=played and bool(row.home_won if is_home else row.away_won),
    )


def _real(row: Any, seeds: dict[str, int], round_code: str, label: str, conference: str) -> Tie:
    return Tie(
        round=round_code,
        round_label=label,
        conference=conference,
        home=_side_from(row, row.home_team, seeds, is_home=True),
        away=_side_from(row, row.away_team, seeds, is_home=False),
        played=bool(row.played),
        game_id=str(row.game_id),
    )


def _slot(seeds_by_seed: dict[int, str], seed: int) -> Side:
    """A wild-card slot: the seeded team if the seeds are known, else the seed."""
    team = seeds_by_seed.get(seed)
    return Side(team=team, seed=seed, label=f"{seed} seed")


def _empty(label: str) -> Side:
    return Side(team=None, seed=None, label=label)


def _scaffold(round_code: str, label: str, conference: str, index: int,
              seeds_by_seed: dict[int, str]) -> Tie:
    """The unplayed shape of one game.

    Only the wild-card round can be filled from seeds. Everything past it
    depends on reseeding — the one seed plays whoever of the survivors finished
    lowest — so those slots say where their teams will come from instead of
    pretending to know.
    """
    if round_code == "WC":
        high, low = WILD_CARD_PAIRS[index]
        return Tie(
            round=round_code,
            round_label=label,
            conference=conference,
            home=_slot(seeds_by_seed, high),
            away=_slot(seeds_by_seed, low),
        )
    if round_code == "DIV":
        # The one seed hosts the lowest surviving seed; the other two winners
        # meet. Which is which is not knowable until the round before is done.
        home = _slot(seeds_by_seed, 1) if index == 0 else _empty("Wild Card winner")
        return Tie(
            round=round_code,
            round_label=label,
            conference=conference,
            home=home,
            away=_empty("Wild Card winner"),
        )
    if round_code == "CON":
        return Tie(
            round=round_code,
            round_label=label,
            conference=conference,
            home=_empty("Divisional winner"),
            away=_empty("Divisional winner"),
        )
    return Tie(
        round=round_code,
        round_label=label,
        conference="",
        home=_empty("AFC champion"),
        away=_empty("NFC champion"),
    )


def _round_games(
    season: Season,
    games: pd.DataFrame,
    seeds: dict[str, int],
    round_code: str,
    label: str,
    per_conference: int,
) -> list[Tie]:
    """Every game of one round: the real ones where they exist, slots elsewhere."""
    real = _played_games(games, round_code)

    if round_code == "SB":
        if real:
            return [_real(real[0], seeds, round_code, label, "")]
        return [_scaffold(round_code, label, "", 0, {})]

    out: list[Tie] = []
    for conference in CONFERENCES:
        seeds_by_seed = _by_seed(seeds, conference, season)
        here = [
            row
            for row in real
            if season.conf_of.get(row.home_team) == conference
        ]
        for index in range(per_conference):
            if index < len(here):
                out.append(_real(here[index], seeds, round_code, label, conference))
            else:
                out.append(_scaffold(round_code, label, conference, index, seeds_by_seed))
    return out


def build(season: Season, games: pd.DataFrame, seeds: dict[str, int] | None) -> list[dict]:
    """The whole bracket, round by round.

    ``seeds`` is whatever the standings currently say — ``None`` or empty
    before anything has been played, which draws the shape with nothing in it.
    """
    seeds = seeds or {}
    return [
        {
            "round": code,
            "label": label,
            "games": _round_games(season, games, seeds, code, label, per_conference),
        }
        for code, label, per_conference in ROUNDS
    ]


def byes(season: Season, seeds: dict[str, int] | None) -> list[dict[str, Any]]:
    """The one seed in each conference, which plays nobody in the first round.

    Named rather than left as an absence: "why is my team not in the wild-card
    round" has exactly one good answer and the bracket should give it.
    """
    seeds = seeds or {}
    out = []
    for conference in CONFERENCES:
        team = _by_seed(seeds, conference, season).get(1)
        out.append({"conference": conference, "team": team, "seed": 1})
    return out
