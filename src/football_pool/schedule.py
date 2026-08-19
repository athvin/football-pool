"""The slate, read through the pool's eyes.

A generic NFL schedule tells you who plays whom. This one tells you what each
game is *worth*, and to whom — which is a different question, because of one
fact from the scoring rules: **a regular-season win pays the winner's own
leveling factor**. So a single game carries two different numbers, one per
side, and the loser's leveling factor never enters into it.

The other thing this module owns is *which week you are looking at*. That is
deliberately derived from kickoff times alone and never from results. The
obvious alternative — the first week with an unplayed game — looks equivalent
and is not: one cancelled or never-reported game pins it to that week for the
rest of the season, and the page would sit on week 4 in December.

Everything here returns plain numbers and dataclasses. The render-shaped dicts
live in ``render.py``, the same split as ``potential.entrant_outlook``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

import pandas as pd

from .nflverse import SCHEDULE_TZ
from .season import Season

# Median NFL game runs about 3h10m; overtime plus a broadcast delay reaches
# roughly 3h50m. The only instant this constant actually moves is the
# Monday-night rollover, and the gap from there to the next week's Thursday
# kickoff is three days — so anything from 0 to ~70h gives the same answer on
# every other day of the week. 3h30m puts the flip just after MNF ends.
GAME_TAIL = timedelta(hours=3, minutes=30)

# An unknown kickoff is read as the last possible moment of its day, so a week
# can never roll over *early* on missing data. Playoff rows arrive before their
# times are set, and upstream fills week 18 with placeholder 13:00s.
UNKNOWN_KICKOFF = "23:59"

ROUND_NAMES = {
    "WC": "Wild Card",
    "DIV": "Divisional",
    "CON": "Conference",
    "SB": "Super Bowl",
}


@dataclass(frozen=True)
class WeekWindow:
    """When one week owns the page. Both instants are UTC."""

    week: int
    game_type: str
    opens: datetime
    closes: datetime

    @property
    def label(self) -> str:
        return week_label(self.week, self.game_type)


def kickoff(gameday: str, gametime: object) -> datetime:
    """The UTC instant one scheduled game starts.

    nflverse dates *and* times every game on the US Eastern clock — including
    the 09:30 London kickoffs, which carry the Sunday they are watched on
    rather than a UK date. Reading them in any other zone puts the day boundary
    in the middle of a slate.
    """
    if gametime is None or (isinstance(gametime, float) and math.isnan(gametime)):
        gametime = UNKNOWN_KICKOFF
    text = str(gametime).strip() or UNKNOWN_KICKOFF
    local = datetime.fromisoformat(f"{gameday}T{text}").replace(tzinfo=SCHEDULE_TZ)
    return local.astimezone(timezone.utc)


def week_windows(games: pd.DataFrame) -> list[WeekWindow]:
    """One window per week, in schedule order, partitioning the timeline.

    A window closes one game after its last kickoff — but never later than the
    next week opens. That clamp is what makes the windows a *total, monotone*
    partition by construction: without it a single rescheduled row (nflverse
    moves ``gameday`` forward on a postponement, and the league has played
    Tuesday games) could push one week's close past the next week's start, and
    the default would skip a week or stick on one. On the real 2026 file the
    clamp never binds — the smallest gap between weeks is about three days — so
    it is insurance, not a correction.
    """
    if games.empty:
        return []

    kicks = [kickoff(row.gameday, row.gametime) for row in games.itertuples()]
    frame = pd.DataFrame(
        {
            "week": games["week"].to_numpy(),
            "game_type": games["game_type"].to_numpy(),
            "kick": kicks,
        }
    )

    rows = []
    for (week, game_type), group in frame.groupby(["week", "game_type"], sort=True):
        # Back to plain datetimes: pandas promotes the column to datetime64, and
        # a Timestamp leaking into the template would serialise differently.
        kicks = [k.to_pydatetime() for k in group["kick"]]
        rows.append(
            WeekWindow(
                week=int(week),
                game_type=str(game_type),
                opens=min(kicks),
                closes=max(kicks) + GAME_TAIL,
            )
        )

    rows.sort(key=lambda w: (w.opens, w.week))
    return [
        WeekWindow(
            week=w.week,
            game_type=w.game_type,
            opens=w.opens,
            closes=min(w.closes, rows[i + 1].opens) if i + 1 < len(rows) else w.closes,
        )
        for i, w in enumerate(rows)
    ]


def default_week(windows: list[WeekWindow], instant: datetime) -> int | None:
    """The week that owns ``instant`` — the first one not yet finished.

    Before the season that is week 1; after the Super Bowl it is the last week,
    which is right, because the last thing that happened is the thing you want
    to look at.
    """
    for window in windows:
        if window.closes > instant:
            return window.week
    return windows[-1].week if windows else None


def week_label(week: int, game_type: str) -> str:
    """``"Week 7"`` in the regular season, the round's name after it."""
    return ROUND_NAMES.get(game_type, f"Week {week}")


def side_points(season: Season, game_type: str, team: str, *, is_home: bool = False) -> float:
    """What ``team`` scores by winning this game from the given side.

    The wild-card round is the odd one, and the side matters there. The bonus
    rewards the *upset*, and because the top seed has a bye, every wild-card
    host is a division winner and every visitor a wild card — so the scoring
    engine awards it exactly when the away team wins, with no seeding lookup.
    The host is therefore playing for nothing, which is a genuinely interesting
    thing for the page to say out loud.
    """
    b = season.bonuses
    if game_type == "REG":
        return round(season.win_multiplier * season.lf_of(team), 2)
    if game_type == "WC":
        return 0.0 if is_home else round(
            b.wild_card_upset_flat
            + (season.lf_of(team) if b.wild_card_upset_add_lf else 0.0),
            2,
        )
    stages = {
        "DIV": (b.divisional_flat, b.divisional_add_lf),
        "CON": (b.conference_flat, b.conference_add_lf),
        "SB": (b.super_bowl_flat, b.super_bowl_add_lf),
    }
    if game_type not in stages:
        return 0.0
    flat, add_lf = stages[game_type]
    return round(flat + (season.lf_of(team) if add_lf else 0.0), 2)


def _deltas(season: Season, game_type: str, home: str, away: str) -> list[float]:
    """Per entrant, points if the away side wins minus points if the home side does."""
    out = []
    for e in season.entrants:
        gain_away = side_points(season, game_type, away) if away in e.teams else 0.0
        gain_home = (
            side_points(season, game_type, home, is_home=True) if home in e.teams else 0.0
        )
        out.append(gain_away - gain_home)
    return out


def game_swing(season: Season, game_type: str, home: str, away: str) -> float:
    """How much this game actually moves the standings.

    Centred on purpose. The naive reading — add up everything everybody stands
    to gain — badly over-rates chalk: when a team half the pool owns wins, half
    the pool rises together and the *order* barely changes. Subtracting the
    mean measures only the part that separates people, which is the same thing
    ``metrics.leverage`` says about picks. A game the whole field holds one
    side of scores exactly zero.
    """
    deltas = _deltas(season, game_type, home, away)
    if not deltas:
        return 0.0
    mean = sum(deltas) / len(deltas)
    return round(sum(abs(d - mean) for d in deltas), 2)


def entrant_stake(season: Season, game_type: str, home: str, away: str, teams: set[str]) -> tuple[float, float]:
    """``(max, min)`` points one entrant can take out of a single game.

    Holding both sides is the case worth getting right: whatever happens they
    score, so the minimum is the worst *outcome* rather than zero — and in the
    regular season the worst outcome can be the tie. ``tie_multiplier`` is
    commissioner-configurable down to 0.0, where a tie pays nothing and a
    min-of-the-two-win-stakes floor overstates what is locked in; that number
    feeds ``guaranteed_extra``, the floor, and the elimination badge, so it
    has to be exact under every config. Playoff games cannot tie, so there
    the win stakes are the whole outcome set.
    """
    home_in, away_in = home in teams, away in teams
    if not home_in and not away_in:
        return 0.0, 0.0

    if home_in and away_in:
        outcomes = [
            side_points(season, game_type, home, is_home=True),
            side_points(season, game_type, away),
        ]
        if game_type == "REG":
            outcomes.append(
                round(season.tie_multiplier * (season.lf_of(home) + season.lf_of(away)), 2)
            )
        return max(outcomes), min(outcomes)

    team = home if home_in else away
    outcomes = [side_points(season, game_type, team, is_home=home_in), 0.0]
    if game_type == "REG":
        # Only ever the maximum under an exotic ``tie_multiplier > win_multiplier``
        # config; the loss keeps the minimum at zero.
        outcomes.append(round(season.tie_multiplier * season.lf_of(team), 2))
    return max(outcomes), min(outcomes)


def teams_on_bye(all_teams: Sequence[str], slate: pd.DataFrame) -> list[str]:
    """Which teams have no game in this slate.

    A bye is the one thing on a schedule that is invisible on the schedule:
    there is no row to read, so an entrant whose team is off simply finds a
    quiet week with no explanation for it. This subtracts, which is the only
    way to see it — everyone in the league who is not playing.

    Deliberately not filtered to the regular season here. The caller knows
    which round it is holding, and the answer for a playoff week (every team
    already knocked out, plus the seeds resting) is a true answer to a
    different question — one no page should ask.
    """
    # A slate with no rows may also have no columns, depending on how it was
    # built. The answer is the same either way and it is not an error: if
    # nobody is playing, everybody is off.
    if slate.empty:
        return sorted(all_teams)
    playing = set(slate["home_team"]) | set(slate["away_team"])
    return sorted(t for t in all_teams if t not in playing)


def week_window(season: Season, slate: pd.DataFrame, teams: set[str]) -> tuple[float, float]:
    """``(max, min)`` points available to ``teams`` across one week's games.

    Takes an already-filtered slate and ignores whether the games were played:
    a week that is over still has to report what *was* on the table, or the
    schedule page would show every past week as worth nothing.
    """
    best = worst = 0.0
    for row in slate.itertuples():
        hi, lo = entrant_stake(season, row.game_type, row.home_team, row.away_team, teams)
        best += hi
        worst += lo
    return round(best, 2), round(worst, 2)
