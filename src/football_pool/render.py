"""Static site generation: pool data in, HTML out.

Every page is server-rendered at build time. The data only changes once a day,
the page has to paint instantly on a phone on bad reception, and a plain HTML
document unfurls correctly when someone drops the link in the family group
chat — all of which argue against shipping a JSON payload and rendering on the
client.

The one real deployment trap is the base path. A GitHub project site is served
from ``/<repo>/``, so a root-absolute ``/assets/site.css`` resolves to the wrong
host path and 404s *only in production*. Every URL therefore goes through the
``url`` filter. A ``<base href>`` tag would be the tempting shortcut, but it
also rewrites in-page anchors like ``href="#scoring"`` into full navigations.
"""

from __future__ import annotations

import json
import shutil
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import history as history_mod
from . import metrics
from . import svg
from .nflverse import GameData
from .potential import entrant_outlook
from .project import Projections, project
from .scoring import entrant_scores, money_if_season_ended, score_teams
from .season import REPO_ROOT, Season
from .standings import final_seeds, playoff_seeds, regular_season_complete, standings_table

TEMPLATE_DIR = REPO_ROOT / "templates"
ASSET_DIR = REPO_ROOT / "assets"


@dataclass(frozen=True)
class SiteContext:
    """Everything the templates need, computed once."""

    season: Season
    games: pd.DataFrame
    data: GameData
    team_points: pd.DataFrame
    standings: pd.DataFrame
    outlook: pd.DataFrame
    history: pd.DataFrame
    seeds: dict[str, int]
    seeds_final: bool
    projections: Projections | None


def build_context(
    season: Season, data: GameData, simulations: int | None = None
) -> SiteContext:
    """Run the whole pipeline once and hand the results to the templates.

    The projection layer is deliberately allowed to fail without taking the
    site down: actual standings are the point, and a modelling problem should
    never cost the family their scoreboard.
    """
    games = data.games
    seeds = final_seeds(season, games)
    team_points = score_teams(season, games, seeds)
    outlook = entrant_outlook(season, games, team_points, seeds)

    scores = entrant_scores(season, team_points)
    outlook = outlook.merge(
        scores[["name", "contributions"]], on="name", how="left"
    )
    outlook["money"] = money_if_season_ended(season, scores).to_numpy()

    try:
        projections = project(season, games, simulations=simulations)
    except Exception as e:  # noqa: BLE001 - a model failure must not break the site
        warnings.warn(f"projections unavailable: {e}", RuntimeWarning, stacklevel=2)
        projections = None

    return SiteContext(
        season=season,
        games=games,
        data=data,
        team_points=team_points,
        standings=standings_table(season, games),
        outlook=outlook,
        history=history_mod.weekly_frame(season, games),
        seeds=seeds if seeds is not None else playoff_seeds(season, games),
        seeds_final=regular_season_complete(games),
        projections=projections,
    )


def make_environment(base: str = "") -> Environment:
    """Jinja environment with the base-path filter and formatting helpers.

    ``StrictUndefined`` turns a typo in a template into a build failure rather
    than a silently blank cell on the leaderboard.
    """
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    prefix = base.rstrip("/")

    def url(path: str) -> str:
        """Resolve a site-root-relative path against the deployment base."""
        if path.startswith(("http://", "https://", "#", "mailto:")):
            return path
        return f"{prefix}/{path.lstrip('/')}"

    def points(value: float | None) -> str:
        """Points always show two decimals so columns line up."""
        return "—" if value is None or pd.isna(value) else f"{float(value):.2f}"

    def money(value: float | None) -> str:
        if value is None or pd.isna(value) or float(value) == 0:
            return ""
        return f"${float(value):,.0f}"

    env.filters.update(url=url, points=points, money=money)
    env.globals.update(
        svg=svg,
        base=prefix,
        now=datetime.now(timezone.utc),
    )
    return env


def _team_card(ctx: SiteContext, team: str) -> dict[str, Any]:
    """One team's summary for an entrant's detail page.

    Built here rather than by indexing DataFrames inside a Jinja template:
    pandas' nullable NA raises on a truthiness test, so template-level
    ``{% if %}`` over a frame cell is a build failure waiting to happen.
    """
    tp = ctx.team_points.loc[team]
    st = ctx.standings.loc[team]
    wins, losses, ties = int(tp["w"]), int(tp["l"]), int(tp["t"])
    return {
        "team": team,
        "lf": float(tp["lf"]),
        "record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
        "points": float(tp["total"]),
        "win_points": float(tp["win_points"]),
        "berth_points": float(tp["berth_points"]),
        "playoff_points": float(tp["playoff_points"]),
        "division": str(st["division"]),
        "seed": None if pd.isna(st["seed"]) else int(st["seed"]),
    }


def _projection_for(ctx: SiteContext, name: str) -> dict[str, Any] | None:
    """One entrant's modelled outcome, or ``None`` when not projecting."""
    if ctx.projections is None:
        return None
    df = ctx.projections.entrants
    match = df[df["name"] == name]
    if match.empty:
        return None

    r = match.iloc[0]
    band = ctx.projections.entrants
    return {
        "p_first": float(r["p_first"]),
        "p_cash": float(r["p_cash"]),
        "expected_payout": float(r["expected_payout"]),
        "expected_net": float(r["expected_net"]),
        "mean_points": float(r["mean_points"]),
        "p10": float(r["p10"]),
        "p50": float(r["p50"]),
        "p90": float(r["p90"]),
        "mean_rank": float(r["mean_rank"]),
        "band": svg.range_bar(
            float(r["p10"]), float(r["p90"]), float(r["mean_points"]),
            float(band["p10"].min()), float(band["p90"].max()),
        ),
        "odds_meter": svg.meter(float(r["p_first"])),
    }


def _entrant_rows(ctx: SiteContext) -> list[dict[str, Any]]:
    """Leaderboard rows, already sorted, with their graphics rendered."""
    scale_max = float(ctx.outlook["ceiling"].max()) if not ctx.outlook.empty else 1.0
    rows = []

    for i, row in enumerate(ctx.outlook.itertuples()):
        series = history_mod.series_for(ctx.history, row.name)
        ranks = history_mod.rank_series_for(ctx.history, row.name)
        delta = (ranks[-2] - ranks[-1]) if len(ranks) >= 2 else 0
        contributions = row.contributions or {}

        rows.append(
            {
                "index": i,
                "rank": int(row.rank),
                "name": row.name,
                "slug": row.slug,
                "teams": list(row.teams),
                "banked": float(row.banked),
                "floor": float(row.floor),
                "ceiling": float(row.ceiling),
                "upside": float(row.upside),
                "guaranteed_extra": float(row.guaranteed_extra),
                "next_week_max": float(row.next_week_max),
                "next_week_min": float(row.next_week_min),
                "money": float(row.money),
                "eliminated": bool(row.eliminated),
                "cash_eliminated": bool(row.cash_eliminated),
                "rank_delta": int(delta),
                "series": series,
                "contributions": contributions,
                "cards": [_team_card(ctx, t) for t in row.teams],
                "projection": _projection_for(ctx, row.name),
                "spark": svg.sparkline(series),
                "bar": svg.outlook_bar(
                    float(row.banked), float(row.guaranteed_extra),
                    float(row.ceiling), scale_max,
                ),
                "contrib": svg.contribution_bar(
                    [(t, float(contributions.get(t, 0.0))) for t in row.teams]
                ),
            }
        )
    return rows


def _pool_state(ctx: SiteContext, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The headline strip: where the season is and who is on top."""
    games = ctx.games
    played = int(games["played"].sum())
    remaining = int((~games["played"]).sum())
    movers = history_mod.movers(ctx.history)
    leaders = history_mod.week_leaders(ctx.season, ctx.history)

    if ctx.data.current_week is None:
        phase = "Preseason"
    elif not ctx.seeds_final:
        phase = f"Week {ctx.data.current_week}"
    elif remaining:
        phase = "Playoffs"
    else:
        phase = "Final"

    return {
        "phase": phase,
        "week": ctx.data.current_week,
        "next_week": ctx.data.next_week,
        "games_played": played,
        "games_remaining": remaining,
        "pot": ctx.season.pot,
        "entrants": len(ctx.season.entrants),
        "leader": rows[0] if rows else None,
        "risers": movers["risers"],
        "fallers": movers["fallers"],
        "week_leaders": leaders,
        "seeds_final": ctx.seeds_final,
    }


def _team_rows(ctx: SiteContext) -> list[dict[str, Any]]:
    """Per-team table, including who in the pool owns each team."""
    owners: dict[str, list[str]] = {t: [] for t in ctx.season.teams}
    for e in ctx.season.entrants:
        for t in e.teams:
            owners[t].append(e.name)

    n = max(len(ctx.season.entrants), 1)
    rows = []
    for team in ctx.season.teams:
        tp = ctx.team_points.loc[team]
        st = ctx.standings.loc[team]
        rows.append(
            {
                "team": team,
                "lf": float(tp["lf"]),
                "w": int(tp["w"]),
                "l": int(tp["l"]),
                "t": int(tp["t"]),
                "record": f"{int(tp['w'])}-{int(tp['l'])}" + (f"-{int(tp['t'])}" if tp["t"] else ""),
                "points": float(tp["total"]),
                "division": st["division"],
                "conference": st["conference"],
                "seed": None if pd.isna(st["seed"]) else int(st["seed"]),
                "owners": owners[team],
                "ownership": len(owners[team]) / n,
            }
        )
    return sorted(rows, key=lambda r: -r["points"])


def _week_rows(ctx: SiteContext, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-entrant week-by-week points and ranks, as plain lists."""
    weeks = ctx.history.attrs.get("weeks", [])
    deltas = history_mod.weekly_deltas(ctx.history)
    out = []
    for r in rows:
        name = r["name"]
        out.append(
            {
                "name": name,
                "slug": r["slug"],
                "total": r["banked"],
                "spark": r["spark"],
                "points": [float(deltas.loc[name, f"w{w}"]) for w in weeks],
                "ranks": [int(ctx.history.loc[name, f"rank_w{w}"]) for w in weeks],
            }
        )
    return out


def _freshness(ctx: SiteContext) -> dict[str, Any]:
    """Two timestamps, because a fresh build of stale data is still stale."""
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_at": (
            ctx.data.upstream_modified.astimezone(timezone.utc).isoformat(timespec="seconds")
            if ctx.data.upstream_modified
            else None
        ),
        "source": ctx.data.source,
    }


def render_site(
    season: Season,
    data: GameData,
    out_dir: Path,
    base: str = "",
    simulations: int | None = None,
) -> list[Path]:
    """Render every page into ``out_dir``. Returns the files written."""
    ctx = build_context(season, data, simulations=simulations)
    env = make_environment(base)

    rows = _entrant_rows(ctx)
    teams = _team_rows(ctx)
    state = _pool_state(ctx, rows)
    fresh = _freshness(ctx)
    weeks = ctx.history.attrs.get("weeks", [])

    shared = {
        "season": season,
        "state": state,
        "fresh": fresh,
        "rows": rows,
        "teams": teams,
        "weeks": weeks,
        "seeds_final": ctx.seeds_final,
        "projecting": ctx.projections is not None,
        "sim_count": ctx.projections.simulations if ctx.projections else 0,
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    # Entrant paths come from the picks file, so a rebuild after someone is
    # removed or renamed would otherwise leave their old page live and
    # reachable. Every other page has a fixed name and is simply overwritten.
    shutil.rmtree(out_dir / "entrant", ignore_errors=True)

    written: list[Path] = []

    def write(rel: str, template: str, **kw) -> None:
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(env.get_template(template).render(**shared, **kw))
        written.append(target)

    write("index.html", "index.html", page="standings")
    write("rules/index.html", "rules.html", page="rules")
    write("teams/index.html", "teams.html", page="teams")
    write("weeks/index.html", "weeks.html", page="weeks", week_rows=_week_rows(ctx, rows))
    write(
        "trends/index.html",
        "trends.html",
        page="trends",
        points_series=[(r["name"], r["series"]) for r in rows if r["series"]],
        rank_series=[
            (r["name"], history_mod.rank_series_for(ctx.history, r["name"]))
            for r in rows
            if r["series"]
        ],
        # Label a handful, not half the field: with six entries, highlighting
        # five would mean nothing is highlighted.
        lead_names=[r["name"] for r in rows[: min(5, max(2, len(rows) // 2))]],
        leverage=metrics.leverage(season).to_dict("records"),
        picks=metrics.pick_report(season, ctx.team_points).to_dict("records"),
        rivals=metrics.rivals(ctx.outlook).to_dict("records"),
    )
    write("404.html", "404.html", page="404")

    for row in rows:
        write(
            f"entrant/{row['slug']}/index.html",
            "entrant.html",
            page="entrant",
            entrant=row,
        )

    # A machine-readable copy of the leaderboard, useful for debugging a build
    # and for anyone who wants to do their own analysis.
    data_path = out_dir / "data" / "standings.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(
        json.dumps(
            {
                "season": season.year,
                "generated": fresh,
                "state": {k: v for k, v in state.items() if k != "leader"},
                "entrants": [
                    {
                        **{
                            k: v
                            for k, v in r.items()
                            if k not in ("spark", "bar", "contrib", "projection", "cards")
                        },
                        "projection": (
                            {
                                k: v
                                for k, v in (r["projection"] or {}).items()
                                if k not in ("band", "odds_meter")
                            }
                            or None
                        ),
                    }
                    for r in rows
                ],
            },
            indent=1,
            default=str,
        )
    )
    written.append(data_path)

    if ASSET_DIR.is_dir():
        target = out_dir / "assets"
        shutil.copytree(ASSET_DIR, target, dirs_exist_ok=True)
        written.extend(sorted(target.rglob("*")))

    return written
