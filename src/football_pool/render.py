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

That filter carries a second production-only job: cache busting. GitHub Pages
serves every file with ``max-age=600`` and gives no way to change it, so for ten
minutes after a deploy a returning visitor holds the previous stylesheet against
markup fetched a moment ago. The skew reads as a layout bug rather than a stale
file — it has already been reported as one. Asset URLs therefore carry a content
fingerprint, which makes a changed file a URL no cache has ever seen. Putting it
in the same filter is the point: a new asset cannot forget to opt in.

With more than one pool on the site, that filter resolves against two prefixes,
and the rule is one sentence: **``/assets/`` belongs to the site, everything
else belongs to the pool.** So there is a single copy of the stylesheet, the
script, the logos and the fonts, linked by the same URL from every pool, while
``/rules/`` under the friends pool means the friends pool's rules. Keep
``/assets/`` the only exception — a page URL that needs to be site-relative and
is not under it would be silently pool-scoped and 404 on the non-root pool only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import bracket as bracket_mod
from . import glossary as glossary_mod
from . import history as history_mod
from . import metrics
from . import schedule as schedule_mod
from . import svg
from . import teamcolors
from .nflverse import GameData
from .potential import entrant_outlook
from .project import Projections, project
from .scoring import entrant_scores, money_if_season_ended, score_teams
from .season import REPO_ROOT, Season
from .standings import final_seeds, playoff_seeds, regular_season_complete, standings_table

TEMPLATE_DIR = REPO_ROOT / "templates"
ASSET_DIR = REPO_ROOT / "assets"

# The `url` filter, passed around as a plain callable. The charts in svg.py draw
# names and team codes that are links now, and a link needs the pool's
# deployment prefix — but there must be exactly one implementation of that
# prefix, so the charts are handed the environment's own closure rather than
# growing a second copy of the rule. See `make_environment`.
UrlFor = Callable[[str], str]

# Long enough that a collision is not a practical concern, short enough to keep
# the markup readable in a diff.
ASSET_HASH_CHARS = 8

# The two links out of the site, in the masthead of every page. The first is
# the arithmetic the forecast is built on, written out in the open; the second
# is what builds the page it is written on. Constants rather than season
# config, because neither is a fact about a season — nothing here changes when
# the year rolls over, and a pool cannot have its own copy of the maths.
MODEL_URL = "https://gist.github.com/datastx/8670c633fd4e44644bfa99c5d0ba1209"
REPO_URL = "https://github.com/athvin/football-pool"


def _root_url(path: str) -> str:
    """What the ``url`` filter returns for a site deployed at the root.

    The default for the helpers that take a resolver, so anything that only
    wants the numbers out of them — a test, mostly — can call one without
    standing up a Jinja environment first. It is never what a real build uses:
    :func:`render_site` always passes the environment's own closure, which is
    the only thing that knows this pool's prefix.
    """
    return path


def _asset_digest(rel: str) -> str:
    """Short content hash of an asset, or ``""`` when there is no such file.

    Hashed from the file's *contents*, deliberately, and never from the build
    time or the commit: a rebuild on a day with no new results has to produce
    the same bytes it produced yesterday, and a timestamp in the URL would put a
    diff on every page. Content hashing also means the offseason months where
    only scores move do not force anyone to re-download the stylesheet.

    A missing file, or a path naming a directory, yields no hash and the URL
    goes out unversioned. That is no worse than it was before fingerprinting
    existed, and a scoreboard should not fail to build because someone deleted a
    favicon.
    """
    target = ASSET_DIR / rel
    if not target.is_file():
        return ""
    return hashlib.sha256(target.read_bytes()).hexdigest()[:ASSET_HASH_CHARS]


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


def make_environment(base: str = "", pool_base: str | None = None) -> Environment:
    """Jinja environment with the base-path filter and formatting helpers.

    ``StrictUndefined`` turns a typo in a template into a build failure rather
    than a silently blank cell on the leaderboard.

    Args:
        base: The deployment prefix — where the *site* lives.
        pool_base: Where this *pool* lives, if it is not at the site root.
            Defaults to ``base``, which is the one-pool case and is exactly
            what this function did before there were two.
    """
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    site_prefix = base.rstrip("/")
    pool_prefix = (pool_base if pool_base is not None else base).rstrip("/")

    # One entry per distinct asset, filled on first reference. Scoped to this
    # environment rather than to the module on purpose: the test suite renders a
    # dozen sites in one process and one of them deliberately points ASSET_DIR
    # somewhere else, so a module-level cache would hand back a digest computed
    # by an earlier test. It also guarantees every page in a build cites the
    # same hash even if a file changes on disk mid-render.
    digests: dict[str, str] = {}

    def url(path: str) -> str:
        """Resolve a root-relative path against the right base.

        ``/assets/`` is the one namespace that belongs to the *site* rather
        than to a pool: there is a single copy of the stylesheet, the script
        and the logos, and every pool links the same URL. Everything else is
        pool-relative, which is what puts the second pool's whole site under
        ``/<slug>/`` without a single template knowing there is more than one.

        Assets additionally carry a content fingerprint — see the module
        docstring for why. The query string is part of the browser's cache key,
        so a changed file simply becomes a URL it has never seen.

        Only ``/assets/`` is fingerprinted. Page URLs are what people paste into
        the group chat, and ``/data/standings.json`` is a documented interface;
        both need to stay stable and clean.
        """
        if path.startswith(("http://", "https://", "#", "mailto:")):
            return path

        if path.startswith("/assets/"):
            resolved = f"{site_prefix}/{path.lstrip('/')}"
            rel = path.removeprefix("/assets/")
            if rel not in digests:
                digests[rel] = _asset_digest(rel)
            if digests[rel]:
                resolved = f"{resolved}?v={digests[rel]}"
            return resolved

        return f"{pool_prefix}/{path.lstrip('/')}"

    def points(value: float | None) -> str:
        """Points always show two decimals so columns line up."""
        return "—" if value is None or pd.isna(value) else f"{float(value):.2f}"

    def money(value: float | None) -> str:
        if value is None or pd.isna(value) or float(value) == 0:
            return ""
        return f"${float(value):,.0f}"

    env.filters.update(
        url=url,
        points=points,
        money=money,
        chip_style=teamcolors.chip_style,
        # One ordinal implementation for the whole site. The hand-rolled
        # template version rendered "21th"/"22th"/"23th" the moment the pool
        # grew past twenty entries; svg._ordinal has always done it right.
        ordinal=svg._ordinal,
    )
    env.globals.update(
        svg=svg,
        base=pool_prefix,
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


def _short_names(names: list[str]) -> dict[str, str]:
    """First names for chart axes, falling back to the full name on a clash.

    "Shannon (plus Si & Rachel)" does not fit a heatmap column header, and the
    full names would force the chart three times wider than the page.
    """
    first = [n.split()[0] if n.split() else n for n in names]
    counts = {f: first.count(f) for f in first}
    return {n: (f if counts[f] == 1 else n) for n, f in zip(names, first)}


def _headline(entrants: pd.DataFrame, column: str) -> dict[str, Any]:
    """Whoever leads on one projection column, with both headline numbers.

    Ties are broken by whoever the frame lists first, which is the model's own
    order — arbitrary, but stable across rebuilds of unchanged data, which is
    what matters for a page that regenerates twice a day.
    """
    best = entrants.loc[entrants[column].idxmax()]
    return {
        "name": str(best["name"]),
        "slug": str(best["slug"]),
        "p_first": float(best["p_first"]),
        "expected_payout": float(best["expected_payout"]),
    }


def _forecast(ctx: SiteContext, url: UrlFor = _root_url) -> dict[str, Any] | None:
    """The three distribution charts, or ``None`` when nothing is projected."""
    p = ctx.projections
    if p is None or p.entrants.empty:
        return None

    # Ordered by chance of winning, so the charts read top to bottom as the
    # model's own ranking rather than as the current standings.
    order = p.entrants.sort_values("p_first", ascending=False)["name"].tolist()
    short = _short_names(order)
    # A name down the side of the grid is the same person as a name in the
    # table below it, so it goes to the same page. Keyed by the full name
    # because that is what the chart is handed; the drawn label may be an
    # abbreviation of it.
    hrefs = {
        row["name"]: url(f"/entrant/{row['slug']}/")
        for _, row in p.entrants.iterrows()
    }

    finish = p.finish_probs.reindex(order)
    h2h = p.head_to_head.reindex(index=order, columns=order)
    money_h2h = p.money_head_to_head.reindex(index=order, columns=order)
    density = p.distribution.density.reindex(order)
    # One indexed copy, rather than re-indexing the frame per entrant inside
    # the comprehensions below.
    by_name = p.entrants.set_index("name")

    return {
        "places": [int(c) for c in finish.columns],
        "finish_rows": [
            {
                "name": name,
                "slug": by_name.loc[name, "slug"],
                "bar": svg.finish_bar(finish.loc[name].tolist()),
                "probs": [float(v) for v in finish.loc[name]],
            }
            for name in order
        ],
        "ridge": svg.ridgeline(
            [float(c) for c in p.distribution.centers],
            [(short[n], density.loc[n].tolist()) for n in order],
            hrefs={short[n]: hrefs[n] for n in order},
        ),
        # NaN on the diagonal becomes None so the template and the chart both
        # read it as "no cell" rather than trying to format a float. Short
        # names are drawn; the full ones ride along for the hover readout,
        # where there is room to say who is actually being compared.
        "heatmap": svg.heatmap(
            [[None if pd.isna(v) else float(v) for v in h2h.loc[n]] for n in order],
            [short[n] for n in order],
            order,
            # Outright odds ride along so the hover readout can say what a
            # pairwise number means for the pool, not just for the pair.
            [float(by_name.loc[n, "p_first"]) * 100 for n in order],
            hrefs=hrefs,
        ),
        # The same pairs, priced. Both grids are drawn at build time and the
        # picker only chooses which one is on screen, so the numbers are the
        # model's either way and the page needs no arithmetic of its own.
        # Outright here is the chance of being paid at all, because that is
        # the question the money grid is a pairwise version of.
        "money_heatmap": svg.heatmap(
            [
                [None if pd.isna(v) else float(v) for v in money_h2h.loc[n]]
                for n in order
            ],
            [short[n] for n in order],
            order,
            [float(by_name.loc[n, "p_cash"]) * 100 for n in order],
            verb="out-earns",
            hrefs=hrefs,
        ),
        # How many places the pot actually reaches, which is what decides how
        # often two entrants are level on money. Truncated to the field: a
        # two-person pool with three payout tiers pays two.
        "paid_places": min(len(ctx.season.payouts), len(order)),
        "order": order,
        # The two headline answers, which are not the same question and do not
        # always have the same answer. Named separately so the page can say so
        # out loud instead of leaving a reader to work out which one the big
        # number at the top of a bar actually is.
        "best_odds": _headline(p.entrants, "p_first"),
        "best_money": _headline(p.entrants, "expected_payout"),
        # What the ratings were fitted to. The page says so plainly rather than
        # describing one method and silently running the other.
        "basis": p.basis,
        "market_games": p.market_games,
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
    slugs = {e.name: e.slug for e in ctx.season.entrants}
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
        "finish_bar": svg.finish_bar(ctx.projections.finish_probs.loc[name].tolist()),
        # Who this entrant is favoured against, best chance first. Their own
        # cell is NaN and drops out. The slug rides along because every one of
        # these names is a link on the page — the same names, one table lower,
        # have always been links, and the two disagreeing was the bug.
        "rivals": [
            {"name": other, "slug": slugs[other], "p": float(v)}
            for other, v in ctx.projections.head_to_head.loc[name]
            .dropna()
            .sort_values(ascending=False)
            .items()
        ],
    }


def _next_week_byes(ctx: SiteContext) -> tuple[int | None, set[str]]:
    """``(week, teams off)`` for the next regular-season week, or ``(None, set())``.

    The same week ``potential.next_week_window`` prices — the first regular
    week with a game still to play — because the entrant page shows the two
    side by side, and a "nothing next week" that quietly meant a different
    week from the bye list would be worse than saying nothing at all.
    """
    remaining = ctx.games[(~ctx.games["played"]) & (ctx.games["game_type"] == "REG")]
    if remaining.empty:
        return None, set()
    week = int(remaining["week"].min())
    slate = ctx.games[(ctx.games["week"] == week) & (ctx.games["game_type"] == "REG")]
    return week, set(schedule_mod.teams_on_bye(ctx.season.teams, slate))


def _entrant_rows(ctx: SiteContext, url: UrlFor = _root_url) -> list[dict[str, Any]]:
    """Leaderboard rows, already sorted, with their graphics rendered."""
    scale_max = float(ctx.outlook["ceiling"].max()) if not ctx.outlook.empty else 1.0
    bye_week, on_bye = _next_week_byes(ctx)
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
                # Which of this entry's four teams are off next week, and which
                # week that is. A bye is the usual reason a "next week" number
                # looks disappointing, and it is the one thing the schedule
                # cannot show you, because a bye has no game to render.
                "bye_week": bye_week,
                "byes": [t for t in row.teams if t in on_bye],
                "series": series,
                "contributions": contributions,
                "cards": [_team_card(ctx, t) for t in row.teams],
                "projection": _projection_for(ctx, row.name),
                "spark": svg.sparkline(series),
                "bar": svg.outlook_bar(
                    float(row.banked), float(row.guaranteed_extra),
                    float(row.ceiling), scale_max,
                ),
                # The four codes written into this bar are the same four teams
                # as the chips in the hero above it, so they go to the same
                # four pages.
                "contrib": svg.contribution_bar(
                    [(t, float(contributions.get(t, 0.0))) for t in row.teams],
                    href_base=url("/team/"),
                ),
            }
        )
    return rows


def _named(
    season: Season, pairs: Sequence[tuple[str, float]], key: str
) -> list[dict[str, Any]]:
    """``(name, number)`` pairs, with the slug that makes the name a link.

    The history and metrics layers deal in names because that is what the
    frames are indexed by, and their tuple shape is asserted by tests that have
    nothing to do with the website. The slug is a fact about a *page*, so it is
    attached here, at the edge where the pool becomes HTML — the same reason
    ``owners`` and ``stakes`` are built with one further down this file.
    """
    slugs = {e.name: e.slug for e in season.entrants}
    return [{"name": n, "slug": slugs[n], key: v} for n, v in pairs if n in slugs]


def _pool_state(ctx: SiteContext, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The headline strip: where the season is and who is on top."""
    games = ctx.games
    played = int(games["played"].sum())
    remaining = int((~games["played"]).sum())
    movers = history_mod.movers(ctx.history)
    leaders = history_mod.week_leaders(ctx.season, ctx.history)
    weeks = ctx.history.attrs.get("weeks", [])

    # "Final" means a played Super Bowl, nothing weaker. In the window between
    # the last week-18 game and nflverse publishing the bracket rows, the file
    # has zero unplayed games — "remaining == 0" would have declared the pool
    # over with the entire postseason still to play.
    sb_done = bool(((games["game_type"] == "SB") & games["played"]).any())

    if ctx.data.current_week is None:
        phase = "Preseason"
    elif not ctx.seeds_final:
        phase = f"Week {ctx.data.current_week}"
    elif sb_done:
        phase = "Final"
    else:
        phase = "Playoffs"

    return {
        "phase": phase,
        "week": ctx.data.current_week,
        # The most recent week anyone scored in — 19-22 during the playoffs,
        # where ``week`` (max REG week) sticks at 18. This is the number the
        # "Best of week N" panel must use, or January points get a week-18
        # headline.
        "scored_week": weeks[-1] if weeks else None,
        # REG games still to play. ``games_remaining`` counts the playoffs
        # too, which is the wrong test for "should projections exist" — the
        # model only simulates the regular season.
        "reg_games_remaining": int(
            ((~games["played"]) & (games["game_type"] == "REG")).sum()
        ),
        "next_week": ctx.data.next_week,
        "games_played": played,
        "games_remaining": remaining,
        "pot": ctx.season.pot,
        "entrants": len(ctx.season.entrants),
        "leader": rows[0] if rows else None,
        "risers": _named(ctx.season, movers["risers"], "change"),
        "fallers": _named(ctx.season, movers["fallers"], "change"),
        "week_leaders": _named(ctx.season, leaders, "points"),
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
                # Sort key for the record column: win percentage, so 10-6-1
                # orders above 10-7 instead of tying with it on raw wins.
                "win_pct": float(st["win_pct"]),
                "points": float(tp["total"]),
                "division": st["division"],
                "conference": st["conference"],
                "seed": None if pd.isna(st["seed"]) else int(st["seed"]),
                "owners": owners[team],
                "ownership": len(owners[team]) / n,
            }
        )
    # Points first, and then the leveling factor. The tie-break is what makes
    # this table readable in August: before a single kickoff every team has
    # scored exactly zero, and sorting on that alone left thirty-two rows in
    # whatever order the league file happened to list them. Falling through to
    # the leveling factor puts the most valuable teams at the top, which is the
    # only ranking that exists in the preseason. The name settles the rest so a
    # rebuild of unchanged data is an unchanged page.
    return sorted(rows, key=lambda r: (-r["points"], -r["lf"], r["team"]))


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


def _eastern(instant: datetime) -> str:
    """A kickoff written the way a broadcast lists it: ``Sun, Sep 13, 1:00 PM EDT``.

    Matches the format the client re-renders it in, so switching time zones
    changes the words in the string but not its shape.
    """
    local = instant.astimezone(schedule_mod.SCHEDULE_TZ)
    return (
        f"{local:%a, %b} {local.day}, "
        f"{local.hour % 12 or 12}:{local:%M %p} {local:%Z}"
    )


def _game_row(
    ctx: SiteContext,
    row: Any,
    owners: dict[str, tuple[str, ...]],
    slugs: dict[str, str],
    short: dict[str, str],
) -> dict[str, Any]:
    """One game, priced and attributed.

    All the frame indexing happens here rather than in the template, per
    ``_team_card`` — and it matters more on this page than anywhere else,
    because scores are nullable ``Int64`` and a bare ``{% if game.home_score %}``
    would raise on an unplayed game *and* hide a shutout.
    """
    season = ctx.season
    home, away, kind = row.home_team, row.away_team, row.game_type
    p = ctx.projections
    rate = None
    if p is not None and row.game_id in p.home_win_rate.index and not row.played:
        rate = float(p.home_win_rate[row.game_id])

    def side(team: str, score: object, is_home: bool) -> dict[str, Any]:
        held = owners.get(team, ())
        if not row.played:
            outcome = None
        elif row.is_tie:
            outcome = "tied"
        else:
            outcome = "won" if row.home_won == is_home else "lost"
        return {
            "team": team,
            "stake": schedule_mod.side_points(season, kind, team, is_home=is_home),
            "score": None if pd.isna(score) else int(score),
            "owners": [{"name": short[n], "slug": slugs[n]} for n in held],
            "p_win": None if rate is None else (rate if is_home else 1.0 - rate),
            "outcome": outcome,
            # Losers desaturate so a finished week reads at a glance. Everything
            # unplayed is drawn as live, because it still could be.
            "chip": "dim" if outcome == "lost" else "scored",
        }

    home_side = side(home, row.home_score, True)
    away_side = side(away, row.away_score, False)

    # What each entrant stands to gain or lose here, keyed by slug so `initMe`
    # can reveal exactly one of them with no extra JavaScript.
    stakes = []
    for e in season.entrants:
        best, worst = schedule_mod.entrant_stake(season, kind, home, away, set(e.teams))
        if best:
            # The name rides along for the expanded panel, which lists everyone
            # with something on this game rather than only the reader.
            stakes.append(
                {"slug": e.slug, "name": short[e.name], "max": best, "min": worst}
            )

    kick = schedule_mod.kickoff(row.gameday, row.gametime)
    return {
        "game_id": row.game_id,
        "kickoff": kick.isoformat(timespec="seconds"),
        # Readable without scripting. The client rewrites it into whichever zone
        # the visitor picked; until then it says Eastern, which is the zone the
        # league schedules in and the site's own default.
        "kickoff_text": _eastern(kick),
        "home": home_side,
        "away": away_side,
        "played": bool(row.played),
        "tie": bool(row.is_tie),
        "home_won": bool(row.home_won),
        "overtime": bool(row.overtime == 1),
        "neutral": row.location == "Neutral",
        "swing": schedule_mod.game_swing(season, kind, home, away),
        "stakes": stakes,
        # Which week this is. The schedule page groups by week and never needs
        # it; a team's own page lists one team's season straight down and has
        # to say where in the season each game sits.
        "week": int(row.week),
        "kind": kind,
        # Nobody in the pool holds either side. A third of the 2026 slate, and
        # dimming it is what turns a 16-game week into the handful that matter.
        "idle": not home_side["owners"] and not away_side["owners"],
        # Pool money on both sides — the games people actually argue about.
        "derby": bool(home_side["owners"] and away_side["owners"]),
    }


def _team_page(ctx: SiteContext, team: str) -> dict[str, Any]:
    """One team's own page: what it has produced, for whom, and every game.

    The season down one column. A team is the unit everybody actually argues
    about — "what has Cincinnati actually done for me" is the question behind
    half the group chat — and until now the answer was spread across a row of
    the teams table, a chip on your own page, and eighteen weeks of schedule.

    Games come through :func:`_game_row`, the same builder the schedule page
    uses, so a game cannot be priced one way here and another way there.
    """
    owners = {t: o.owners for t, o in metrics.ownership(ctx.season).items()}
    slugs = {e.name: e.slug for e in ctx.season.entrants}
    short = _short_names([e.name for e in ctx.season.entrants])

    games = ctx.games[
        (ctx.games["home_team"] == team) | (ctx.games["away_team"] == team)
    ]
    rows = [_game_row(ctx, r, owners, slugs, short) for r in games.itertuples()]
    rows.sort(key=lambda g: (g["week"], g["kickoff"]))

    # The bye, named where it falls. A season list that jumps from week 5 to
    # week 7 has told you nothing about week 6, and "my team did nothing that
    # week" is the single most common thing a bye is mistaken for. Regular
    # season only: in January, "not playing" describes two dozen teams that are
    # simply out, which is a different sentence.
    reg = ctx.games[ctx.games["game_type"] == "REG"]
    playing = {g["week"] for g in rows}
    season_rows: list[dict[str, Any]] = [
        *rows,
        *(
            {"bye": True, "week": int(w), "kickoff": "", "played": False}
            for w in sorted(set(reg["week"].astype(int)) - playing)
        ),
    ]
    season_rows.sort(key=lambda g: (g["week"], g["kickoff"]))

    # What this team is worth to the people holding it. The points are the same
    # number for all of them — a team scores what it scores — but the share of
    # a total is not, and that is the part worth printing: the same 12 points
    # is a quarter of one entry and a twentieth of another.
    held = []
    for row in ctx.outlook.itertuples():
        if team not in row.teams:
            continue
        points = float((row.contributions or {}).get(team, 0.0))
        banked = float(row.banked)
        share = (points / banked) if banked > 0 else 0.0
        held.append(
            {
                "name": row.name,
                "slug": row.slug,
                "points": points,
                "banked": banked,
                "share": share,
                # Banked, so green — this is what the team has actually put in
                # the bag, and cyan on this site means a number the model made
                # up. The one rule the palette has.
                "bar": svg.meter(share, width=240, height=10, fill=svg.BANKED),
            }
        )
    held.sort(key=lambda o: (-o["share"], o["name"]))

    card = _team_card(ctx, team)
    played = [g for g in rows if g["played"]]
    return {
        **card,
        # The season as it reads, byes included; and the count of things that
        # are actually games, which is what "3 of 17 played" is counting.
        "season": season_rows,
        "games": rows,
        "owners": held,
        "played": len(played),
        # The biggest swing among this team's own games, which is what the
        # accent rail on each row is drawn against. Its own season, not the
        # league's: a rail scaled to the biggest game in football would leave
        # a bad team's page with eighteen invisible rails.
        "swing_scale": max((g["swing"] for g in rows), default=0.0),
        "next": next((g for g in rows if not g["played"]), None),
    }


def _bracket(ctx: SiteContext) -> dict[str, Any]:
    """The January bracket, priced.

    :mod:`bracket` builds the football and knows nothing about pools; the
    pricing is added here, because what a playoff win is worth is a fact about
    the rules file and a fact about who is holding the team. Every side
    therefore carries what winning that game pays and who in this pool collects
    it — which is the only reason a pool site should draw a bracket at all
    rather than linking to one.
    """
    season = ctx.season
    owners = {t: o.owners for t, o in metrics.ownership(season).items()}
    slugs = {e.name: e.slug for e in season.entrants}
    short = _short_names([e.name for e in season.entrants])

    def price(side: Any, round_code: str, *, is_home: bool) -> dict[str, Any]:
        """One side, with what a win there pays and who it pays."""
        held = owners.get(side.team, ()) if side.team else ()
        return {
            "team": side.team,
            "seed": side.seed,
            "label": side.label,
            "score": side.score,
            "won": side.won,
            # The wild-card round pays the *upset*, so the host is playing for
            # nothing at all — a genuinely interesting thing for a bracket to
            # say, and the reason this is per side rather than per game.
            "stake": (
                schedule_mod.side_points(season, round_code, side.team, is_home=is_home)
                if side.team
                else None
            ),
            "owners": [{"name": short[n], "slug": slugs[n]} for n in held],
        }

    rounds = []
    for round_ in bracket_mod.build(season, ctx.games, ctx.seeds):
        rounds.append(
            {
                "round": round_["round"],
                "label": round_["label"],
                "games": [
                    {
                        "round": tie.round,
                        "conference": tie.conference,
                        "played": tie.played,
                        "known": tie.known,
                        "game_id": tie.game_id,
                        "home": price(tie.home, tie.round, is_home=True),
                        "away": price(tie.away, tie.round, is_home=False),
                    }
                    for tie in round_["games"]
                ],
            }
        )

    resting = [
        {
            **b,
            "owners": [
                {"name": short[n], "slug": slugs[n]} for n in owners.get(b["team"], ())
            ]
            if b["team"]
            else [],
        }
        for b in bracket_mod.byes(season, ctx.seeds)
    ]

    return {
        "rounds": rounds,
        "byes": resting,
        # Whether the field is settled or still a projection. The whole bracket
        # is one or the other and the page has to say which, because a
        # projected wild-card matchup drawn like a fixture is a lie told in
        # good faith.
        "final": ctx.seeds_final,
        "seeded": bool(ctx.seeds),
    }


def _schedule(ctx: SiteContext) -> dict[str, Any]:
    """Every week of the slate, and which one to open on.

    The default week is resolved from ``fetched_at`` rather than the wall
    clock: it keeps a rebuild of unchanged data byte-identical, and the client
    re-runs the identical rule against the visitor's own clock anyway, which is
    the reading that actually matters.
    """
    games = ctx.games
    owners = {t: o.owners for t, o in metrics.ownership(ctx.season).items()}
    slugs = {e.name: e.slug for e in ctx.season.entrants}
    short = _short_names([e.name for e in ctx.season.entrants])
    windows = schedule_mod.week_windows(games)

    weeks = []
    for window in windows:
        slate = games[games["week"] == window.week]
        rows = [_game_row(ctx, r, owners, slugs, short) for r in slate.itertuples()]
        # The frame arrives sorted by (week, gameday, game_id) — within one
        # Sunday that is matchup-alphabetical, which rendered the night game
        # above the afternoon slate (57 inversions across the 2026 file).
        # Kickoffs are ISO-8601 UTC strings, so lexicographic is chronological.
        rows.sort(key=lambda g: g["kickoff"])
        # "Field maximum" has to mean what it says: the most the pool can
        # actually bank. A side nobody holds is not on anyone's table — taking
        # the bigger side of every game counted 233 phantom points across the
        # 2026 slate, and every fully idle game inflated its week.
        on_the_table = round(
            sum(
                max((s["stake"] for s in (g["home"], g["away"]) if s["owners"]), default=0.0)
                for g in rows
            ),
            2,
        )

        outlooks = []
        for e in ctx.season.entrants:
            best, worst = schedule_mod.week_window(ctx.season, slate, set(e.teams))
            outlooks.append(
                {"name": short[e.name], "slug": e.slug, "max": best, "min": worst}
            )
        ceiling = max((o["max"] for o in outlooks), default=0.0) or 1.0

        # Only the regular season has byes worth naming. In January "not
        # playing this week" describes two dozen eliminated teams, which is a
        # true sentence about something nobody is asking.
        byes = (
            [
                {
                    "team": t,
                    "owners": [
                        {"name": short[n], "slug": slugs[n]} for n in owners.get(t, ())
                    ],
                }
                for t in schedule_mod.teams_on_bye(ctx.season.teams, slate)
            ]
            if window.game_type == "REG"
            else []
        )
        # Teams somebody holds first: an entrant scanning the week wants to
        # know their own team is off, not that the Jets are.
        byes.sort(key=lambda b: (not b["owners"], b["team"]))

        weeks.append(
            {
                "week": window.week,
                "label": window.label,
                "byes": byes,
                "opens": window.opens.isoformat(timespec="seconds"),
                "opens_text": _eastern(window.opens),
                "closes": window.closes.isoformat(timespec="seconds"),
                "games": rows,
                "count": len(rows),
                "pool_games": sum(1 for g in rows if not g["idle"]),
                "on_the_table": on_the_table,
                # Points the field cannot avoid banking: when one entrant holds
                # both sides of a game, somebody they own has to win it.
                "locked_in": round(sum(o["min"] for o in outlooks), 2),
                "played": sum(1 for g in rows if g["played"]),
                "biggest": max(rows, key=lambda g: g["swing"], default=None),
                "outlooks": [
                    {
                        **o,
                        "bar": svg.outlook_bar(
                            0.0, o["min"], o["max"], ceiling,
                            label=f"{o['name']}: guaranteed {o['min']:.2f}, up to {o['max']:.2f}",
                        ),
                    }
                    for o in outlooks
                ],
            }
        )

    return {
        "weeks": weeks,
        "default_week": schedule_mod.default_week(windows, ctx.data.fetched_at),
    }


def _deadlines(ctx: SiteContext) -> dict[str, Any] | None:
    """When picks and money are due, read off the schedule itself.

    The rules page states two deadlines — picks in before the season's first
    kickoff, payment in by the end of week 1 — and both are dates the NFL
    owns, not the pool. Deriving them from the same games file the scoring
    engine reads keeps the posted deadline correct for any season the site is
    asked to build, including a rebuilt archive year.
    """
    reg = ctx.games[ctx.games["game_type"] == "REG"]
    if reg.empty:
        return None
    week1 = reg[reg["week"] == int(reg["week"].min())]
    kicks = sorted(
        schedule_mod.kickoff(r.gameday, r.gametime) for r in week1.itertuples()
    )
    first, last = kicks[0], kicks[-1]

    last_local = last.astimezone(schedule_mod.SCHEDULE_TZ)
    return {
        # ISO so the client can rewrite it into the visitor's own zone —
        # a deadline is the one number on the site that must not be off by
        # three hours — with the Eastern rendering as the scripting-off text.
        "picks_due": first.isoformat(timespec="seconds"),
        "picks_due_text": _eastern(first),
        # "End of week 1" means the night its last game is played. A date, not
        # an instant: nobody schedules money to the minute.
        "payment_due_date": f"{last_local:%A, %B} {last_local.day}",
    }


# How each fetch outcome reads to somebody who does not know the pipeline.
# "cache" and "fallback" both mean the build could not reach upstream, and the
# difference between them — a copy from an earlier run versus the snapshot
# committed to the repo — is exactly the difference between hours and months.
SOURCE_TEXT = {
    "network": "live from nflverse",
    "cache": "a cached copy — upstream was unreachable",
    "fallback": "the committed snapshot — upstream was unreachable",
}


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
        "source_text": SOURCE_TEXT.get(ctx.data.source, ctx.data.source),
    }


def render_site(
    season: Season,
    data: GameData,
    out_dir: Path,
    base: str = "",
    simulations: int | None = None,
    *,
    site_base: str | None = None,
    copy_assets: bool = True,
) -> list[Path]:
    """Render one pool's every page into ``out_dir``. Returns the files written.

    Args:
        base: Where this pool lives — the prefix every page URL gets.
        site_base: Where the *site* lives, which is where ``/assets/`` resolves
            against. Defaults to ``base``: for a site with one pool the two are
            the same, and this behaves exactly as it did before there were two.
        copy_assets: Whether to copy ``assets/`` alongside the pages. False when
            a caller is rendering several pools and will copy them once, at the
            site root — see :func:`render_pools`.
    """
    ctx = build_context(season, data, simulations=simulations)
    env = make_environment(site_base if site_base is not None else base, pool_base=base)

    # The templates reach the same function through the `url` filter. The charts
    # are built here in Python and cannot, so they are handed the filter itself
    # — one implementation of the deployment prefix, not two.
    url: UrlFor = env.filters["url"]

    rows = _entrant_rows(ctx, url)
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
        "forecast": _forecast(ctx, url),
        # Definitions carry this season's own entry fee, pot and payout places,
        # so the explanation of a word can never drift from the rules file that
        # sets it. See glossary.py.
        "glossary": glossary_mod.terms(season),
        "model_url": MODEL_URL,
        "repo_url": REPO_URL,
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    # Entrant paths come from the picks file, so a rebuild after someone is
    # removed or renamed would otherwise leave their old page live and
    # reachable. Team paths come from rules.yaml and are just as capable of
    # changing under a rebuild. Every other page has a fixed name and is simply
    # overwritten.
    shutil.rmtree(out_dir / "entrant", ignore_errors=True)
    shutil.rmtree(out_dir / "team", ignore_errors=True)

    written: list[Path] = []

    def write(rel: str, template: str, **kw) -> None:
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(env.get_template(template).render(**shared, **kw))
        written.append(target)

    write("index.html", "index.html", page="standings")
    write(
        "schedule/index.html",
        "schedule.html",
        page="schedule",
        schedule=_schedule(ctx),
        bracket=_bracket(ctx),
    )
    write("forecast/index.html", "forecast.html", page="forecast")
    write("rules/index.html", "rules.html", page="rules", deadlines=_deadlines(ctx))
    write("teams/index.html", "teams.html", page="teams")
    # Weeks and Trends merged into one Season page: what happened and how it
    # moved are one story, and six tabs was three too many for a family pool.
    # The old addresses live in a year of group-chat links, so they forward.
    write("weeks/index.html", "redirect.html", page="weeks", target="/season/")
    write("trends/index.html", "redirect.html", page="trends", target="/season/")
    write(
        "season/index.html",
        "season.html",
        page="season",
        week_rows=_week_rows(ctx, rows),
        points_series=[(r["name"], r["series"]) for r in rows if r["series"]],
        rank_series=[
            (r["name"], history_mod.rank_series_for(ctx.history, r["name"]))
            for r in rows
            if r["series"]
        ],
        # The same numbers again, carrying each entrant's slug, because the
        # comparison chart is picked by slug — the identity the whole site
        # already uses for URLs and for "this is me".
        compare_points=[(r["name"], r["slug"], r["series"]) for r in rows if r["series"]],
        compare_ranks=[
            (r["name"], r["slug"], history_mod.rank_series_for(ctx.history, r["name"]))
            for r in rows
            if r["series"]
        ],
        # Label a handful, not half the field: with six entries, highlighting
        # five would mean nothing is highlighted.
        lead_names=[r["name"] for r in rows[: min(5, max(2, len(rows) // 2))]],
        # The two chart families on this page are labelled with people's names,
        # and a name is a link. `compare_lines` already carries the slug in its
        # own data and only needs to know where /entrant/ lives; the emphasis
        # charts are handed names alone, so they get the finished URLs.
        entrant_href_base=url("/entrant/"),
        entrant_hrefs={r["name"]: url(f"/entrant/{r['slug']}/") for r in rows},
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

    # One page per team, per pool. The football on them is identical — a team
    # scores what it scores, whoever is watching — but the people are not, and
    # a friends-pool page naming a family-pool owner would put a hole straight
    # through the wall between the two.
    for team in season.teams:
        write(
            f"team/{team}/index.html",
            "team.html",
            page="team",
            team=_team_page(ctx, team),
        )

    # A machine-readable copy of the leaderboard, useful for debugging a build
    # and for anyone who wants to do their own analysis.
    data_path = out_dir / "data" / "standings.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(
        json.dumps(
            {
                "season": season.year,
                "pool": {
                    "slug": season.pool.slug,
                    "name": season.pool.name,
                    "path": season.pool.path,
                    "entry_fee": season.entry_fee,
                    "pot": season.pot,
                },
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
                                # Rendered SVG is markup, not data. It belongs
                                # on the page, not in the machine-readable feed
                                # — it tripled the file the one time it leaked.
                                if k not in ("band", "odds_meter", "finish_bar")
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

    if copy_assets:
        written.extend(_copy_assets(out_dir))

    return written


def _copy_assets(out_dir: Path) -> list[Path]:
    """Copy ``assets/`` to ``out_dir/assets``. One copy serves the whole site."""
    if not ASSET_DIR.is_dir():
        return []
    target = out_dir / "assets"
    shutil.copytree(ASSET_DIR, target, dirs_exist_ok=True)
    return sorted(target.rglob("*"))


def render_pools(
    seasons: Sequence[Season],
    data: GameData,
    out_dir: Path,
    base: str = "",
    simulations: int | None = None,
) -> list[Path]:
    """Render every pool into one site. The root pool owns the site root.

    Each pool is a complete site under its own prefix — its own leaderboard,
    entrant pages and standings feed. The only thing they share on disk is
    ``/assets/``, which is why the ``url`` filter resolves an asset against the
    site and a page against the pool.

    Deliberately, no page in one pool links to another pool. The pools share a
    domain as an implementation detail, not an experience: each group gets one
    URL, and nobody lands on a roster that has no idea who they are.
    """
    site_base = base.rstrip("/")

    written: list[Path] = []
    for s in seasons:
        path = s.pool.path
        written += render_site(
            s,
            data,
            # Path(out) / "" is Path(out), so the root pool needs no special case.
            out_dir / path if path else out_dir,
            base=f"{site_base}/{path}" if path else site_base,
            simulations=simulations,
            site_base=site_base,
            copy_assets=False,
        )

    written.extend(_copy_assets(out_dir))
    return written
