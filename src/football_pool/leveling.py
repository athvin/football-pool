"""Deriving and checking leveling factors from the prior season.

The commissioner sets the leveling factors, and this module never overrides
them — a table that disagreed with the official sheet by even 0.15 would
misscore everyone for a whole season. What it does is reconstruct the structure
so a new year can be proposed in seconds and an existing table can be checked
for transcription errors.

The structure, recovered from the 2026 table against real 2025 records:

* Each conference is ranked by prior-season wins, a tie counting as half a win.
* Leveling factor rises monotonically down that ranking — worse team, more
  points per win.
* Clubs with identical records share an identical factor.

That reproduces 31 of 32 values exactly. The lone exception is New England
(1.10) and Denver (1.20), both 14-3, where the tie appears to have been broken
on how far each went in January.

The gist's ``lf_linear`` — ``3.05 - 0.136 * wins`` — describes this curve well
(R² > .95) but reproduces none of the 32 values exactly, so it is a summary of
the shape rather than the rule that generates it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .season import Season


@dataclass(frozen=True)
class LevelingIssue:
    """Something about a leveling-factor table that a human should look at."""

    kind: str  # "not-monotonic" or "tie-mismatch"
    conference: str
    detail: str


def prior_season_wins(season: Season, prior_games: pd.DataFrame) -> dict[str, float]:
    """Wins per team last season, counting a tie as half a win."""
    from .nflverse import team_records

    rec = team_records(prior_games, season.teams)
    return {t: float(rec.loc[t, "w"] + 0.5 * rec.loc[t, "t"]) for t in season.teams}


def conference_ranking(season: Season, wins: dict[str, float], conference: str) -> list[str]:
    """Teams in a conference, best record first.

    Equal records are ordered by team code so the ranking is stable across
    runs; where the factors differ inside a tie the commissioner has applied a
    tiebreak this module does not attempt to guess.
    """
    return sorted(season.conference_teams(conference), key=lambda t: (-wins[t], t))


def check_leveling_factors(
    season: Season, prior_games: pd.DataFrame
) -> list[LevelingIssue]:
    """Check a configured table against the prior season's records.

    Catches the realistic failure — a value mistyped or a row transposed while
    copying the commissioner's sheet — without asserting that the exact
    numbers are derivable.
    """
    wins = prior_season_wins(season, prior_games)
    issues: list[LevelingIssue] = []

    for conf in ("AFC", "NFC"):
        ranked = conference_ranking(season, wins, conf)

        previous_team, previous_lf = None, 0.0
        for team in ranked:
            lf = season.lf_of(team)
            if lf < previous_lf - 1e-9:
                issues.append(
                    LevelingIssue(
                        kind="not-monotonic",
                        conference=conf,
                        detail=(
                            f"{team} ({wins[team]:.1f} wins, LF {lf:.2f}) is rated "
                            f"easier than {previous_team} "
                            f"({wins[previous_team]:.1f} wins, LF {previous_lf:.2f}) "
                            f"despite the worse record"
                        ),
                    )
                )
            previous_team, previous_lf = team, lf

        by_record: dict[float, list[str]] = {}
        for team in ranked:
            by_record.setdefault(wins[team], []).append(team)

        for record, group in sorted(by_record.items()):
            factors = {season.lf_of(t) for t in group}
            if len(factors) > 1:
                shown = ", ".join(f"{t} {season.lf_of(t):.2f}" for t in group)
                issues.append(
                    LevelingIssue(
                        kind="tie-mismatch",
                        conference=conf,
                        detail=(
                            f"{record:.1f} wins: {shown} — same record, different "
                            f"factors (a deliberate tiebreak, or a typo)"
                        ),
                    )
                )

    return issues


def propose_leveling_factors(
    season: Season, prior_games: pd.DataFrame, ladder: dict[str, list[float]] | None = None
) -> dict[str, float]:
    """Propose next season's table from last season's finish.

    Keeps the shape of the existing table — the same sorted run of values in
    each conference — and reassigns it by the new standings, giving equal
    records equal factors.

    This is a starting point to check against the commissioner's sheet, never a
    replacement for it. ``pool check-lf`` will tell you where the two differ.
    """
    wins = prior_season_wins(season, prior_games)
    proposed: dict[str, float] = {}

    for conf in ("AFC", "NFC"):
        ranked = conference_ranking(season, wins, conf)
        values = (
            list(ladder[conf])
            if ladder
            else sorted(season.lf_of(t) for t in season.conference_teams(conf))
        )
        if len(values) != len(ranked):
            raise ValueError(
                f"{conf}: need {len(ranked)} leveling factors, got {len(values)}"
            )

        # Walk the ladder, but hold the value steady across an equal record.
        index = 0
        for position, team in enumerate(ranked):
            if position > 0 and wins[team] != wins[ranked[position - 1]]:
                index = position
            proposed[team] = values[index]

    return proposed


def comparison_table(
    season: Season, prior_games: pd.DataFrame
) -> pd.DataFrame:
    """Configured factors beside what the structure would propose."""
    wins = prior_season_wins(season, prior_games)
    proposed = propose_leveling_factors(season, prior_games)

    rows = []
    for conf in ("AFC", "NFC"):
        for rank, team in enumerate(conference_ranking(season, wins, conf), start=1):
            rows.append(
                {
                    "team": team,
                    "conference": conf,
                    "rank": rank,
                    "prior_wins": wins[team],
                    "configured": season.lf_of(team),
                    "proposed": proposed[team],
                    "delta": round(season.lf_of(team) - proposed[team], 2),
                }
            )
    return pd.DataFrame(rows).set_index("team")
