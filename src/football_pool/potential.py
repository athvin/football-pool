"""What is still reachable: next week, the ceiling, the floor, elimination.

Two structural facts drive everything here, and getting either wrong makes the
numbers quietly nonsense:

**Your own teams play each other.** A four-team entry averages about 3.25 games
per season in which two of that entry's own teams meet, and essentially every
entry has at least one. So a "sum of LF" potential double-counts (both teams
cannot win), and — more interestingly — every entrant has a *guaranteed* future
haul, because somebody has to win those games.

**Playoff structure binds.** A team earns the division bonus or the wild-card
bonus, never both. Two of your teams in one division cannot both win it. Only
two teams per conference can win a divisional-round game, only one can win the
conference, and only one team in the league wins the Super Bowl. A ceiling that
ignores this is far too high, which would make the elimination badge lie.

The ceiling here is a true upper bound: it assumes every remaining game breaks
your way, subject only to constraints that are structurally impossible to beat.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product

import pandas as pd

from .schedule import entrant_stake, week_window
from .season import Season

@dataclass(frozen=True)
class Outlook:
    """One entrant's banked, guaranteed, next-week and ceiling numbers."""

    name: str
    slug: str
    banked: float
    guaranteed_extra: float  # future points that cannot be avoided
    next_week_max: float
    next_week_min: float
    ceiling: float

    @property
    def floor(self) -> float:
        """Worst case final score — banked plus unavoidable future points."""
        return round(self.banked + self.guaranteed_extra, 2)

    @property
    def upside(self) -> float:
        """How much is still on the table above the floor."""
        return round(self.ceiling - self.floor, 2)


def _remaining_regular_games(games: pd.DataFrame) -> pd.DataFrame:
    return games[(~games["played"]) & (games["game_type"] == "REG")]


def head_to_head_games(games: pd.DataFrame, teams: set[str]) -> pd.DataFrame:
    """Remaining games where two of ``teams`` play each other."""
    rem = _remaining_regular_games(games)
    return rem[rem["home_team"].isin(teams) & rem["away_team"].isin(teams)]


def guaranteed_extra(season: Season, games: pd.DataFrame, teams: set[str]) -> float:
    """Points the entrant will earn no matter how the games go.

    When two of your teams meet, the game pays you whatever happens — a win
    either way, or the tie — so the smallest of those outcomes is already
    banked. ``entrant_stake`` prices the tie explicitly, which keeps this
    floor honest even when the commissioner sets ``tie_multiplier: 0``.
    """
    total = 0.0
    for row in head_to_head_games(games, teams).itertuples():
        total += entrant_stake(season, row.game_type, row.home_team, row.away_team, teams)[1]
    return round(total, 2)


def next_week_window(season: Season, games: pd.DataFrame, teams: set[str]) -> tuple[float, float]:
    """``(max, min)`` regular-season points available to ``teams`` next week.

    Byes score nothing. If two of the entrant's teams meet, the best case is the
    larger stake and the worst case is the smaller — not their sum.
    """
    rem = _remaining_regular_games(games)
    if rem.empty:
        return 0.0, 0.0
    return week_window(season, rem[rem["week"] == int(rem["week"].min())], teams)


def remaining_win_points(season: Season, games: pd.DataFrame, teams: set[str]) -> float:
    """Most regular-season points still winnable, respecting head-to-head games."""
    return week_window(season, _remaining_regular_games(games), teams)[0]


# How far a team got. Higher is deeper; the values are cumulative milestones.
DEPTH_MISSED = 0  # did not make the playoffs
DEPTH_IN_FIELD = 1  # earned a berth
DEPTH_WON_DIVISIONAL = 2
DEPTH_WON_CONFERENCE = 3
DEPTH_WON_SUPER_BOWL = 4

_ROUND_DEPTH = {"DIV": DEPTH_WON_DIVISIONAL, "CON": DEPTH_WON_CONFERENCE, "SB": DEPTH_WON_SUPER_BOWL}


@dataclass(frozen=True)
class PlayoffState:
    """Where a team currently stands in the bracket."""

    berth: str | None  # "DW", "WC", or None
    depth: int
    won_wild_card: bool
    eliminated: bool


def playoff_progress(
    season: Season, games: pd.DataFrame, seeds: dict[str, int] | None
) -> dict[str, PlayoffState]:
    """Each team's current bracket position, from completed playoff games.

    Before the field is settled every team is unresolved, which is what lets the
    ceiling assume the best case during the regular season.
    """
    if seeds is None:
        return {}

    state = {
        t: PlayoffState(
            berth=("DW" if s <= 4 else "WC"), depth=DEPTH_IN_FIELD,
            won_wild_card=False, eliminated=False,
        )
        for t, s in seeds.items()
    }

    po = games[games["played"] & games["game_type"].isin(("WC", "DIV", "CON", "SB"))]
    for row in po.itertuples():
        if row.is_tie:  # impossible in the playoffs; never guess
            continue
        winner = row.home_team if row.home_won else row.away_team
        loser = row.away_team if row.home_won else row.home_team

        if loser in state:
            state[loser] = replace(state[loser], eliminated=True)
        if winner in state:
            cur = state[winner]
            if row.game_type == "WC":
                # The away team is always the wild card; a home win pays nothing.
                state[winner] = replace(cur, won_wild_card=bool(row.away_won))
            else:
                state[winner] = replace(cur, depth=max(cur.depth, _ROUND_DEPTH[row.game_type]))
    return state


def _depth_points(season: Season, team: str, berth: str, depth: int, won_wc: bool) -> float:
    """Total postseason points for a team that reached ``depth``."""
    b = season.bonuses
    lf = season.lf_of(team)
    if depth < DEPTH_IN_FIELD:
        return 0.0

    total = b.division_winner if berth == "DW" else b.wild_card_berth
    if berth == "WC" and won_wc:
        total += b.wild_card_upset_flat + (lf if b.wild_card_upset_add_lf else 0.0)
    if depth >= DEPTH_WON_DIVISIONAL:
        total += b.divisional_flat + (lf if b.divisional_add_lf else 0.0)
    if depth >= DEPTH_WON_CONFERENCE:
        total += b.conference_flat + (lf if b.conference_add_lf else 0.0)
    if depth >= DEPTH_WON_SUPER_BOWL:
        total += b.super_bowl_flat + (lf if b.super_bowl_add_lf else 0.0)
    return total


def max_postseason_points(
    season: Season,
    teams: set[str],
    seeds: dict[str, int] | None = None,
    progress: dict[str, PlayoffState] | None = None,
) -> float:
    """Best structurally-possible postseason haul across an entrant's teams.

    Enumerates every feasible outcome and takes the best. With four teams the
    search space is a few thousand rows, so exhaustive search is exact and
    instant.

    Three levels of knowledge tighten the answer as the season progresses:
    during the regular season every berth is still possible; once ``seeds`` are
    known each team is pinned to the berth it earned and non-qualifiers score
    zero; once ``progress`` is supplied, teams already knocked out cannot gain
    another point, so a finished season collapses the ceiling onto the result.
    """
    team_list = sorted(teams)
    if not team_list:
        return 0.0

    options: list[list[tuple[str | None, int, bool]]] = []
    for team in team_list:
        options.append(_team_options(season, team, seeds, progress))

    best = 0.0
    for combo in product(*options):
        if not _feasible(season, team_list, combo):
            continue
        best = max(
            best,
            sum(
                _depth_points(season, t, berth, depth, won_wc)
                for t, (berth, depth, won_wc) in zip(team_list, combo)
                if berth is not None
            ),
        )
    return round(best, 2)


def _team_options(
    season: Season,
    team: str,
    seeds: dict[str, int] | None,
    progress: dict[str, PlayoffState] | None,
) -> list[tuple[str | None, int, bool]]:
    """Every postseason outcome still available to one team."""
    depths = range(DEPTH_IN_FIELD, DEPTH_WON_SUPER_BOWL + 1)

    if seeds is None:  # regular season — any berth is still reachable
        opts: list[tuple[str | None, int, bool]] = [(None, DEPTH_MISSED, False)]
        opts += [("DW", d, False) for d in depths]
        opts += [("WC", d, True) for d in depths]
        return opts

    seed = seeds.get(team)
    if seed is None:
        return [(None, DEPTH_MISSED, False)]

    berth = "DW" if seed <= 4 else "WC"
    state = (progress or {}).get(team)
    if state is None:
        return [(berth, d, berth == "WC") for d in depths]

    # Already banked progress is the floor; elimination pins it as the ceiling.
    reachable = [state.depth] if state.eliminated else list(range(state.depth, DEPTH_WON_SUPER_BOWL + 1))
    won_wc = state.won_wild_card if (state.eliminated or berth == "DW") else True
    return [(berth, d, won_wc) for d in reachable]


def _feasible(
    season: Season, teams: list[str], combo: tuple[tuple[str | None, int, bool], ...]
) -> bool:
    """Whether a set of postseason outcomes could all happen in one bracket."""
    div_winners: dict[str, int] = {}
    per_conf_wc: dict[str, int] = {}
    per_conf_div_round: dict[str, int] = {}
    per_conf_conf_title: dict[str, int] = {}
    super_bowl_winners = 0

    for team, (berth, depth, _) in zip(teams, combo):
        if berth is None:
            continue
        conf = season.conf_of[team]
        if berth == "DW":
            div = season.div_of[team]
            div_winners[div] = div_winners.get(div, 0) + 1
            if div_winners[div] > 1:
                return False  # one champion per division
            # No separate per-conference cap is needed: one champion per
            # division across four divisions already caps a conference at four.
        else:
            per_conf_wc[conf] = per_conf_wc.get(conf, 0) + 1
            if per_conf_wc[conf] > 3:
                return False  # three wild cards per conference

        if depth >= DEPTH_WON_DIVISIONAL:
            per_conf_div_round[conf] = per_conf_div_round.get(conf, 0) + 1
            if per_conf_div_round[conf] > 2:
                return False  # only two divisional games per conference
        if depth >= DEPTH_WON_CONFERENCE:
            per_conf_conf_title[conf] = per_conf_conf_title.get(conf, 0) + 1
            if per_conf_conf_title[conf] > 1:
                return False
        if depth >= DEPTH_WON_SUPER_BOWL:
            super_bowl_winners += 1
            if super_bowl_winners > 1:
                return False

    return True


def berth_points_already_banked(
    season: Season, team_points: pd.DataFrame, teams: set[str]
) -> float:
    """Berth and playoff points an entrant has already locked in."""
    cols = ["berth_points", "playoff_points"]
    return float(team_points.loc[sorted(teams), cols].to_numpy().sum())


def entrant_outlook(
    season: Season,
    games: pd.DataFrame,
    team_points: pd.DataFrame,
    seeds: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Banked / floor / next week / ceiling for every entrant, best first."""
    from .scoring import entrant_scores

    scores = entrant_scores(season, team_points)
    progress = playoff_progress(season, games, seeds)
    rows = []

    for row in scores.itertuples():
        teams = set(row.teams)
        banked = float(row.total)
        guaranteed = guaranteed_extra(season, games, teams)
        nw_max, nw_min = next_week_window(season, games, teams)

        # The ceiling adds every remaining win plus the best possible postseason,
        # minus any berth/playoff points already counted in `banked` (those are
        # re-derived inside max_postseason_points).
        already = berth_points_already_banked(season, team_points, teams)
        ceiling = round(
            banked
            - already
            + remaining_win_points(season, games, teams)
            + max_postseason_points(season, teams, seeds, progress),
            2,
        )

        rows.append(
            Outlook(
                name=row.name,
                slug=row.slug,
                banked=banked,
                guaranteed_extra=guaranteed,
                next_week_max=nw_max,
                next_week_min=nw_min,
                ceiling=ceiling,
            )
        )

    df = pd.DataFrame(
        {
            "name": [o.name for o in rows],
            "slug": [o.slug for o in rows],
            "rank": scores["rank"].to_numpy(),
            "teams": scores["teams"].to_numpy(),
            "banked": [o.banked for o in rows],
            "guaranteed_extra": [o.guaranteed_extra for o in rows],
            "floor": [o.floor for o in rows],
            "next_week_max": [o.next_week_max for o in rows],
            "next_week_min": [o.next_week_min for o in rows],
            "ceiling": [o.ceiling for o in rows],
            "upside": [o.upside for o in rows],
        }
    )
    return add_elimination(df)


def add_elimination(outlook: pd.DataFrame) -> pd.DataFrame:
    """Flag entrants whose ceiling cannot reach the field's best floor.

    Mathematical elimination is a hard fact: if the best you can possibly finish
    is below what someone else is already guaranteed, you cannot catch them.
    In practice this cannot fire until around week 15, so the site also shows a
    softer simulation-based badge once projections are available.
    """
    if outlook.empty:
        outlook["eliminated"] = []
        outlook["cash_eliminated"] = []
        return outlook

    floors = outlook["floor"].to_numpy()
    ceilings = outlook["ceiling"].to_numpy()

    # Beaten by someone whose floor already exceeds your ceiling.
    outlook["eliminated"] = [
        bool(((floors > c) & (outlook.index != i)).any()) for i, c in enumerate(ceilings)
    ]
    # Out of the money: at least three others are already guaranteed to beat you.
    outlook["cash_eliminated"] = [
        int(((floors > c) & (outlook.index != i)).sum()) >= 3
        for i, c in enumerate(ceilings)
    ]
    return outlook
