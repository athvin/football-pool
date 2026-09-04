"""Command line entry point.

    pool standings          # current leaderboard in the terminal
    pool fetch              # refresh the cached games file
    pool build              # generate the static site into public/

Every command takes ``--season``; it defaults to ``active_season`` in
config.yaml, so pinning a past year is just ``--season 2026``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .nflverse import STALE_DAYS_LIMIT
from .season import REPO_ROOT, ConfigError, active_season, load_season


def data_dir(season: int, root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / "data" / str(season)


def games_cache(season: int, root: Path | None = None) -> Path:
    return data_dir(season, root) / "games.csv"


def roster_cache(season: int, root: Path | None = None) -> Path:
    return data_dir(season, root) / "roster.csv"


def _fetch_roster(year: int, offline: bool):
    """The roster feed, which is allowed to be missing.

    A thin seam over :func:`rosters.fetch_roster` mostly so it is one thing to
    stub: the roster is context, not results, and no test of scoring or
    publishing should need the network to say so. Lives under the same daily
    ``data/`` commit as the games cache, so the fallback refreshes itself.
    """
    from .rosters import fetch_roster

    return fetch_roster(year, cache_path=roster_cache(year), offline=offline)


def _load(args) -> tuple:
    """Load season config and games together — the common prologue."""
    from .nflverse import fetch_games, validate_teams

    # One positional argument unless a pool was actually named: asking for the
    # root pool by name and getting it by default are the same request, and
    # keeping the call shape means nothing that stubs load_season has to care.
    slug = getattr(args, "pool", None)
    season = load_season(args.season, pool=slug) if slug else load_season(args.season)
    gd = fetch_games(
        season.year,
        cache_path=games_cache(season.year),
        offline=getattr(args, "offline", False),
    )
    validate_teams(gd.games, season.teams)
    return season, gd


def cmd_fetch(args) -> int:
    from .nflverse import fetch_games, validate_teams

    year = args.season if args.season is not None else active_season()
    gd = fetch_games(year, cache_path=games_cache(year), offline=args.offline)
    played = int(gd.games["played"].sum())
    print(f"season {year}: {len(gd.games)} games, {played} played  [{gd.source}]")
    if gd.upstream_modified:
        print(f"upstream last modified: {gd.upstream_modified.isoformat()}")

    rd = _fetch_roster(year, args.offline)
    if rd is not None:
        print(f"roster: {len(rd.players)} players  [{rd.source}]")
    else:
        # Expected all spring — upstream publishes roster_<year>.csv when the
        # league year opens — and never a failure: the roster decorates pages,
        # it does not score them.
        print("roster: unavailable (the site builds without it)")
    return 0


def cmd_standings(args) -> int:
    from .scoring import entrant_scores, money_if_season_ended, score_teams
    from .standings import final_seeds

    season, gd = _load(args)
    # Without the seeds, the terminal leaderboard never awarded the +3.0
    # division and +1.5 wild-card bonuses — it disagreed with the site all
    # January, by up to two division winners per entry.
    tp = score_teams(season, gd.games, final_seeds(season, gd.games))
    st = entrant_scores(season, tp)
    st["money"] = money_if_season_ended(season, st)

    week = gd.current_week
    header = f"{season.year} {season.pool.name}"
    header += f" — through week {week}" if week else " — preseason, no games played"
    print(f"\n{header}")
    print(f"{len(season.entrants)} entrants · pot ${season.pot:,.0f}\n")

    print(f"{'#':>3}  {'entrant':<22}{'pts':>8}  {'$':>7}  teams")
    for row in st.itertuples():
        teams = " ".join(
            f"{t}({row.contributions[t]:g})" for t in row.teams
        )
        money = f"${row.money:,.0f}" if row.money else ""
        print(f"{row.rank:>3}  {row.name:<22}{row.total:>8.2f}  {money:>7}  {teams}")
    print()
    return 0


def cmd_check_lf(args) -> int:
    """Check the configured leveling factors against last season's records."""
    from .leveling import check_leveling_factors, comparison_table
    from .nflverse import fetch_games, validate_teams

    season = load_season(args.season)
    prior_year = args.prior or season.year - 1
    prior = fetch_games(prior_year, cache_path=games_cache(prior_year), offline=args.offline)
    validate_teams(prior.games, season.teams)

    table = comparison_table(season, prior.games)
    issues = check_leveling_factors(season, prior.games)

    print(f"\n{season.year} leveling factors vs {prior_year} records\n")
    print(f"{'':4}{'team':6}{'W':>6}{'configured':>12}{'proposed':>10}{'delta':>8}")
    for conf in ("AFC", "NFC"):
        print(f"  -- {conf} --")
        for team, row in table[table["conference"] == conf].iterrows():
            flag = "  <--" if row["delta"] else ""
            print(
                f"{int(row['rank']):>4}{team:>6}{row['prior_wins']:>6.1f}"
                f"{row['configured']:>12.2f}{row['proposed']:>10.2f}"
                f"{row['delta']:>+8.2f}{flag}"
            )

    matched = int((table["delta"] == 0).sum())
    print(f"\n{matched}/{len(table)} match the structure derived from {prior_year}.")

    if issues:
        print(f"\n{len(issues)} thing(s) worth a look:")
        for issue in issues:
            print(f"  [{issue.conference} {issue.kind}] {issue.detail}")
        print(
            "\nThese are not necessarily wrong — the commissioner may have applied a "
            "deliberate tiebreak. Check them against the official sheet."
        )
    else:
        print("\nNothing inconsistent found.")
    return 0


def _sibling_pools(season) -> tuple:
    """Every other pool sharing this season, in registry order.

    Empty for a season that declares one pool — which is every archived year,
    and every season a test builds — so the single-pool path stays exactly the
    path it was on before.
    """
    if len(season.pools) <= 1 or season.config_root is None:
        return ()
    from .season import load_pools

    return tuple(
        s
        for s in load_pools(season.year, root=season.config_root)
        if s.pool.slug != season.pool.slug
    )


def cmd_build(args) -> int:
    from .render import render_pools

    season, gd = _load(args)

    # Publishing stale numbers is worse than not publishing. The site's whole
    # promise is that the leaderboard is current, and a silently wrong board
    # looks exactly like a correct one — whereas a skipped deploy leaves
    # yesterday's good site up and fixes itself on the next run.
    #
    # The test is the data, not where it came from. A 200 is not the same as
    # good data: a regenerated release asset or a stale CDN object answers
    # perfectly while carrying no results, so checking only fallbacks would wave
    # that straight through. Provenance is the *exemption* — an explicit
    # --offline build is a deliberate request for the committed copy, and is how
    # CI builds deterministically all season.
    if gd.source != "cache" and gd.days_behind >= STALE_DAYS_LIMIT:
        print(
            f"\nrefusing to publish: the results data is {gd.days_behind} days "
            f"behind [{gd.source}].\n"
            f"  Publishing it would replace a correct leaderboard with a stale "
            f"one, which is indistinguishable from a correct one to anyone "
            f"reading it.\n"
            f"  The previous build stays live, and the next run self-heals once "
            f"the feed catches up.\n"
            f"  If this persists, the committed copy under data/{season.year}/ "
            f"is not being refreshed — see DATA_PUSH_TOKEN in the README.\n",
            file=sys.stderr,
        )
        # Distinct from 1, which is a config error, so a red run says which of
        # the two happened without anyone opening the log.
        return 3

    out = Path(args.out) if args.out else REPO_ROOT / "public"

    # A project site lives at https://<user>.github.io/<repo>/, so every URL
    # needs that prefix. CI passes it in; locally the default of "" is right
    # because a preview server serves from the root.
    #
    # --pool renders that pool into its real subpath, so a partial build is
    # always a subset of the real site rather than a differently-shaped one.
    # Fetched after the staleness gate on purpose: a build that is refusing to
    # publish has no reason to spend a network round-trip decorating it.
    roster = _fetch_roster(season.year, args.offline)

    seasons = (season,) if getattr(args, "pool", None) else (season, *_sibling_pools(season))
    written = render_pools(seasons, gd, out, base=args.base, roster=roster)

    pages = sum(1 for p in written if p.suffix == ".html")
    print(f"built {pages} pages for {season.year} -> {out}")
    if len(seasons) > 1:
        for s in seasons:
            print(
                f"  {s.pool.name}: {len(s.entrants)} entries, pot ${s.pot:,.0f}"
                f" -> /{s.pool.path}"
            )
    if gd.current_week:
        print(f"through week {gd.current_week} ({gd.source})")
    else:
        print(f"preseason, no games played yet ({gd.source})")
    return 0


def main(argv: list[str] | None = None) -> int:
    # The shared flags live on a parent parser so they work on either side of
    # the subcommand: `pool --season 2026 build` and `pool build --season 2026`
    # both do the same thing, because people reach for the second form.
    # SUPPRESS is load-bearing: with a real default, the subparser would always
    # write its own default over whatever the main parser already parsed, so
    # `pool --season 2025 fetch` would silently operate on the wrong year.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--season",
        type=int,
        default=argparse.SUPPRESS,
        help="season to operate on (default: active_season from config.yaml)",
    )
    common.add_argument(
        "--offline",
        action="store_true",
        default=argparse.SUPPRESS,
        help="use the committed games file, do not hit the network",
    )

    ap = argparse.ArgumentParser(prog="pool", description=__doc__, parents=[common])
    sub = ap.add_subparsers(dest="command", parser_class=argparse.ArgumentParser)

    def add(name: str, help_text: str, fn):
        p = sub.add_parser(name, help=help_text, parents=[common])
        p.set_defaults(fn=fn)
        return p

    # --pool goes on the two commands that are about one pool's people and
    # money. check-lf is entirely about leveling factors, which are shared by
    # every pool in the season, and fetch never loads a season at all.
    add("fetch", "refresh the cached games file", cmd_fetch)

    standings = add("standings", "print the current leaderboard", cmd_standings)
    standings.add_argument(
        "--pool", default=None, help="which pool to print (default: the one at the site root)"
    )

    check = add(
        "check-lf", "check the leveling factors against last season's records", cmd_check_lf
    )
    check.add_argument(
        "--prior", type=int, default=None, help="season to compare against (default: previous)"
    )

    build = add("build", "generate the static site", cmd_build)
    build.add_argument("--out", default=None, help="output directory (default: public/)")
    build.add_argument(
        "--base",
        default="",
        help="deployment path prefix, e.g. /football-pool (default: site root)",
    )
    build.add_argument(
        "--pool", default=None, help="build only this pool (default: every pool in the season)"
    )

    args = ap.parse_args(argv)
    # SUPPRESS means the attribute is absent unless the flag was actually given.
    args.season = getattr(args, "season", None)
    args.offline = getattr(args, "offline", False)

    if not getattr(args, "fn", None):
        ap.print_help()
        return 2

    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"\nconfig error:\n  {e}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
