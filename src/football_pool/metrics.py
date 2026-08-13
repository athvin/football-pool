"""The fun numbers — the ones that make the site worth opening on a Monday.

Nothing here changes anyone's score. These are readings of the same data the
leaderboard already computes, chosen because they answer the questions people
actually ask each other: who is really in this, whose picks were smart, and
what would have to happen.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .season import Season


@dataclass(frozen=True)
class Ownership:
    """Who holds each team, and how much of the field that represents."""

    team: str
    owners: tuple[str, ...]
    share: float

    @property
    def is_unique(self) -> bool:
        return len(self.owners) == 1

    @property
    def is_chalk(self) -> bool:
        """Held by more than half the pool — its points barely move the standings."""
        return self.share > 0.5


def ownership(season: Season) -> dict[str, Ownership]:
    """Map every team to the entrants holding it."""
    held: dict[str, list[str]] = {t: [] for t in season.teams}
    for e in season.entrants:
        for t in e.teams:
            held[t].append(e.name)

    n = max(len(season.entrants), 1)
    return {
        t: Ownership(team=t, owners=tuple(who), share=len(who) / n)
        for t, who in held.items()
    }


def leverage(season: Season) -> pd.DataFrame:
    """How much of each entry is genuinely their own.

    A team half the pool owns is nearly dead weight: when it wins, most of the
    field moves together and the standings barely change. Points only separate
    you from the field when they come from teams other people do not have, so
    leverage is the leveling factor an entrant holds exclusively.
    """
    held = ownership(season)
    rows = []
    for e in season.entrants:
        unique = [t for t in e.teams if held[t].is_unique]
        shared = [t for t in e.teams if not held[t].is_unique]
        rows.append(
            {
                "name": e.name,
                "slug": e.slug,
                "unique_teams": unique,
                "shared_teams": shared,
                "leverage": round(sum(season.lf_of(t) for t in unique), 2),
                "overlap": round(
                    sum(held[t].share for t in e.teams) / len(e.teams), 3
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("leverage", ascending=False).reset_index(drop=True)


def pick_report(season: Season, team_points: pd.DataFrame) -> pd.DataFrame:
    """Each entrant's best and worst pick so far, against what it cost them.

    "Worst" is measured against the other teams in the same entry, not against
    the league — the interesting question is which of *your* four is carrying
    you and which is sitting on its hands.
    """
    rows = []
    for e in season.entrants:
        points = {t: float(team_points.loc[t, "total"]) for t in e.teams}
        best = max(points, key=points.get)
        worst = min(points, key=points.get)
        total = sum(points.values())
        rows.append(
            {
                "name": e.name,
                "slug": e.slug,
                "best_team": best,
                "best_points": round(points[best], 2),
                "best_share": round(points[best] / total, 3) if total else 0.0,
                "worst_team": worst,
                "worst_points": round(points[worst], 2),
            }
        )
    return pd.DataFrame(rows)


def rivals(outlook: pd.DataFrame) -> pd.DataFrame:
    """Gap to the leader, and the nearest entrant in either direction."""
    ordered = outlook.sort_values("banked", ascending=False).reset_index(drop=True)
    leader = float(ordered.loc[0, "banked"]) if len(ordered) else 0.0

    rows = []
    for i, row in ordered.iterrows():
        ahead = ordered.loc[i - 1] if i > 0 else None
        behind = ordered.loc[i + 1] if i + 1 < len(ordered) else None
        rows.append(
            {
                "name": row["name"],
                "slug": row["slug"],
                "gap_to_leader": round(leader - float(row["banked"]), 2),
                "chasing": None if ahead is None else ahead["name"],
                "chasing_gap": None if ahead is None else round(float(ahead["banked"]) - float(row["banked"]), 2),
                "chased_by": None if behind is None else behind["name"],
                "chased_gap": None if behind is None else round(float(row["banked"]) - float(behind["banked"]), 2),
            }
        )

    df = pd.DataFrame(rows)
    # pandas turns None into NaN, and NaN is *truthy* in a template — the
    # leader's "chasing" cell would render as "nan by nan". Put real Nones back.
    for col in ("chasing", "chasing_gap", "chased_by", "chased_gap"):
        df[col] = df[col].astype(object).where(df[col].notna(), None)
    return df


def team_leaderboard(season: Season, team_points: pd.DataFrame) -> pd.DataFrame:
    """Teams ranked by points generated, with how the pool is exposed to them."""
    held = ownership(season)
    df = team_points.copy()
    df["owners"] = [len(held[t].owners) for t in df.index]
    df["share"] = [held[t].share for t in df.index]
    df["points_per_win"] = df["lf"]
    return df.sort_values("total", ascending=False)


def pool_summary(season: Season, team_points: pd.DataFrame, outlook: pd.DataFrame) -> dict:
    """Headline facts about the field as a whole."""
    held = ownership(season)
    owned = {t: o for t, o in held.items() if o.owners}
    chalk = sorted(
        (o for o in owned.values() if o.share > 0.5),
        key=lambda o: (-o.share, o.team),
    )
    unowned = sorted(t for t, o in held.items() if not o.owners)
    lev = leverage(season)

    return {
        "teams_in_play": len(owned),
        "teams_unowned": unowned,
        "most_owned": chalk[0].team if chalk else None,
        "most_owned_share": chalk[0].share if chalk else 0.0,
        "chalk_teams": [o.team for o in chalk],
        "highest_leverage": lev.iloc[0]["name"] if len(lev) else None,
        "lowest_leverage": lev.iloc[-1]["name"] if len(lev) else None,
        "spread": round(
            float(outlook["banked"].max() - outlook["banked"].min()), 2
        ) if len(outlook) else 0.0,
    }
