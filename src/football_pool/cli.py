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

from .season import REPO_ROOT, ConfigError, active_season, load_season


def data_dir(season: int, root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / "data" / str(season)


def games_cache(season: int, root: Path | None = None) -> Path:
    return data_dir(season, root) / "games.csv"


def _load(args) -> tuple:
    """Load season config and games together — the common prologue."""
    from .nflverse import fetch_games, validate_teams

    season = load_season(args.season)
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
    return 0


def cmd_standings(args) -> int:
    from .scoring import entrant_scores, money_if_season_ended, score_teams

    season, gd = _load(args)
    tp = score_teams(season, gd.games)
    st = entrant_scores(season, tp)
    st["money"] = money_if_season_ended(season, st)

    week = gd.current_week
    header = f"{season.year} pool"
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


# How many overdue games mean the data is behind by a slate rather than by a
# single late upload. Measured, not guessed: replaying a real season a day at a
# time, the count is 0 for the first four days, 1 for the next three — the lone
# Thursday game of the following week — and then jumps straight to 13 once a
# Sunday has been missed. Anything in that empty band works; this sits in the
# middle of it, so an unusual week's scheduling cannot drift across the line.
STALE_GAME_LIMIT = 8


def cmd_build(args) -> int:
    from .render import render_site

    season, gd = _load(args)

    # Publishing stale numbers is worse than not publishing. The site's whole
    # promise is that the leaderboard is current, and a silently wrong board
    # looks exactly like a correct one — whereas a skipped deploy leaves
    # yesterday's good site up and fixes itself on the next run.
    #
    # Only a *fallback* is blocked. An explicit --offline build is a deliberate
    # request for the committed copy and is how CI builds deterministically.
    if gd.source == "fallback" and gd.overdue >= STALE_GAME_LIMIT:
        print(
            f"\nrefusing to publish: could not reach the results feed, and the "
            f"committed copy in data/{season.year}/ is behind by "
            f"{gd.overdue} games.\n"
            f"  Publishing it would replace a correct leaderboard with a stale "
            f"one, which is indistinguishable from a correct one to anyone "
            f"reading it.\n"
            f"  The previous build stays live. The next run self-heals once the "
            f"feed is reachable.\n"
            f"  If this persists, the committed copy is not being refreshed — "
            f"see DATA_PUSH_TOKEN in the README.\n",
            file=sys.stderr,
        )
        return 1

    out = Path(args.out) if args.out else REPO_ROOT / "public"

    # A project site lives at https://<user>.github.io/<repo>/, so every URL
    # needs that prefix. CI passes it in; locally the default of "" is right
    # because a preview server serves from the root.
    written = render_site(season, gd, out, base=args.base)

    pages = sum(1 for p in written if p.suffix == ".html")
    print(f"built {pages} pages for {season.year} -> {out}")
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

    add("fetch", "refresh the cached games file", cmd_fetch)
    add("standings", "print the current leaderboard", cmd_standings)

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
