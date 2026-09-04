"""Team rosters, from the nflverse published CSV.

The same shape as :mod:`nflverse` — one HTTPS GET of one release asset, a
committed cache as the fallback — but the opposite posture toward failure.
Results are load-bearing: stale results block every pool. A roster is context:
who is on the field, who is on injured reserve, who is stashed on the practice
squad. Nothing here can reach a score, so nothing here may stop a publish.
Every failure mode — network down, file missing, schema changed, season not
published yet — degrades to the cached copy, and past that to no roster at
all, which renders as a team page without a roster section.

"Season not published yet" is a real state, not an error: upstream creates
``roster_<season>.csv`` when the league year opens, so asking for a future
season 404s all spring. The build must shrug at that the same way it shrugs at
an outage.
"""

from __future__ import annotations

import io
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .season import TEAM_ALIASES

ROSTER_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{season}.csv"
)

# Everything the team page renders. The upstream file carries thirty-odd
# columns of ids and biography; taking only these keeps the committed cache
# small and makes a schema change upstream a warning here, never a failure.
COLUMNS = [
    "season",
    "team",
    "position",
    "jersey_number",
    "status",
    "full_name",
    "years_exp",
    "college",
    "pfr_id",
]

# The roster file spells two clubs differently from the games file — AZ where
# the schedule says ARI, LA where the pool says LAR. Extended rather than
# replacing TEAM_ALIASES so the two boundaries can never disagree about a code
# they both see.
ROSTER_TEAM_ALIASES = {**TEAM_ALIASES, "AZ": "ARI", "LA": "LAR"}

# Roster statuses, translated. Three fates worth distinguishing on the page:
# on the field (ACT), on the team but not playing (the reserve lists), and on
# the practice squad (DEV). Codes in OFF_TEAM mean the player is gone — cut or
# released — and a "roster" listing them would name more ex-players than
# players by December.
ACTIVE = "ACT"
PRACTICE_SQUAD = "DEV"
OFF_TEAM = frozenset({"CUT", "RLS", "RET", "TRC"})
STATUS_LABELS = {
    "RES": "injured reserve",
    "PUP": "PUP",
    "SUS": "suspended",
    "RSN": "non-football injury",
    "NON": "non-football injury",
    "EXE": "exempt",
    "RSR": "retired",
}

# Field order, offense to special teams — the order a broadcast reads a roster
# in, and the initial sort of the table. The roster file speaks in position
# groups (OL, DL, DB) rather than individual spots, which is exactly the
# granularity a pool page wants. Unknown codes sort last rather than raising:
# upstream adding a position group must not cost anyone their team page.
POSITION_ORDER = ("QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "K", "P", "LS")

PFR_URL = "https://www.pro-football-reference.com/players/{initial}/{pid}.htm"


@dataclass(frozen=True)
class RosterData:
    """Season-filtered players plus the same provenance games carry."""

    players: pd.DataFrame
    season: int
    fetched_at: datetime
    # "network" / "cache" / "fallback", with the meanings nflverse.GameData
    # gives them. Carried for the page's freshness line; unlike the games
    # source it can never stop a publish.
    source: str


class RosterError(Exception):
    """The bytes did not look like a roster. Internal — callers get None."""


def fetch_roster(
    season: int,
    cache_path: Path | None = None,
    *,
    offline: bool = False,
    retries: int = 3,
    timeout: float = 30.0,
) -> RosterData | None:
    """Fetch the roster for ``season``, or ``None`` when there is nothing usable.

    Mirrors :func:`nflverse.fetch_games` — network first, committed cache as
    the fallback, cache refreshed only from good network data — except that
    where the games fetch raises, this returns ``None``. The caller renders a
    site without rosters, which is last year's site, not a broken one.
    """
    import httpx

    raw: bytes | None = None
    source = "fallback"

    if not offline:
        for attempt in range(retries):
            try:
                resp = httpx.get(
                    ROSTER_URL.format(season=season),
                    follow_redirects=True,
                    timeout=timeout,
                    headers={"Accept-Encoding": "gzip"},
                )
                resp.raise_for_status()
                raw = resp.content
                source = "network"
                break
            except Exception:  # noqa: BLE001 - retried, then degraded, never raised
                if attempt < retries - 1:
                    time.sleep(2**attempt)

    players: pd.DataFrame | None = None
    if raw is not None:
        try:
            players = parse_roster(raw, season)
        except Exception as e:  # noqa: BLE001 - a bad roster must not break the site
            warnings.warn(f"roster upstream unusable: {e}", RuntimeWarning, stacklevel=2)
            players = None

    if players is None:
        if cache_path is None or not cache_path.exists():
            return None
        try:
            players = parse_roster(cache_path.read_bytes(), season)
        except Exception as e:  # noqa: BLE001
            warnings.warn(f"roster cache unusable: {e}", RuntimeWarning, stacklevel=2)
            return None
        source = "cache" if offline else "fallback"

    data = RosterData(
        players=players,
        season=season,
        fetched_at=datetime.now(timezone.utc),
        source=source,
    )

    # Refresh the cache only from parsed network data, and atomically, for the
    # same reasons the games cache does: a 200 is not the same as good data,
    # and a killed run must not leave a truncated file that reads back cleanly.
    if source == "network" and cache_path is not None and not players.empty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        partial = cache_path.with_suffix(cache_path.suffix + ".partial")
        players.to_csv(partial, index=False)
        partial.replace(cache_path)

    return data


def parse_roster(raw: bytes | str | Path, season: int) -> pd.DataFrame:
    """Parse the roster CSV, filter to ``season``, and normalize team codes.

    The second boundary where upstream codes become pool codes — held to the
    same rule as the first (see ``nflverse.parse_games``): everything
    downstream speaks pool codes only.
    """
    if isinstance(raw, Path):
        df = pd.read_csv(raw, usecols=lambda c: c in COLUMNS, low_memory=False)
    else:
        data = raw.encode() if isinstance(raw, str) else raw
        df = pd.read_csv(io.BytesIO(data), usecols=lambda c: c in COLUMNS, low_memory=False)

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise RosterError(
            f"upstream roster file is missing expected column(s) {missing}"
        )

    df = df[df["season"] == season].copy()
    if df.empty:
        raise RosterError(f"no players found for season {season}")

    df["team"] = df["team"].replace(ROSTER_TEAM_ALIASES)
    # Ex-players out at the boundary, so nothing downstream can accidentally
    # list them as the roster.
    df = df[~df["status"].isin(OFF_TEAM)]

    # Jersey numbers arrive as float64/NaN — an unassigned number is normal in
    # camp — and Int64 keeps them integral, nullable, and sortable.
    df["jersey_number"] = df["jersey_number"].astype("Int64")
    df["years_exp"] = df["years_exp"].astype("Int64")

    return df.sort_values(["team", "position", "full_name"]).reset_index(drop=True)


def _player(row: Any) -> dict[str, Any]:
    """One player, template-ready — the nullable-NA handling lives here."""
    pos = str(row.position)
    order = POSITION_ORDER.index(pos) if pos in POSITION_ORDER else len(POSITION_ORDER)
    pid = None if pd.isna(row.pfr_id) else str(row.pfr_id)
    return {
        "name": str(row.full_name),
        "pos": pos,
        "pos_order": order,
        "jersey": None if pd.isna(row.jersey_number) else int(row.jersey_number),
        "college": None if pd.isna(row.college) else str(row.college),
        # Seasons of experience, so 0 is a rookie — worth a word on the page
        # rather than a zero.
        "years": None if pd.isna(row.years_exp) else int(row.years_exp),
        # Pro Football Reference's URL scheme bakes the shard directory into
        # the id itself, so the id alone is a working link. A player without
        # one (mostly rookies and camp bodies) renders as plain text.
        "pfr_url": PFR_URL.format(initial=pid[0], pid=pid) if pid else None,
    }


def team_roster(players: pd.DataFrame, team: str) -> dict[str, Any] | None:
    """One team's roster, shaped for the page: active, sidelined, stashed.

    Returns ``None`` for a team the frame has nobody for, which renders the
    same as having no roster data at all — a page without the section.
    """
    mine = players[players["team"] == team]
    if mine.empty:
        return None

    def rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
        out = [_player(r) for r in frame.itertuples()]
        # Field order, then jersey number, then name: the order a reader scans
        # a roster in, with the unnumbered sorted after 99 rather than first.
        out.sort(key=lambda p: (p["pos_order"], p["jersey"] if p["jersey"] is not None else 100, p["name"]))
        return out

    active = rows(mine[mine["status"] == ACTIVE])
    squad = rows(mine[mine["status"] == PRACTICE_SQUAD])

    reserve = mine[~mine["status"].isin({ACTIVE, PRACTICE_SQUAD})]
    sidelined = []
    for r in reserve.itertuples():
        # An unknown code still names a real player on a real list, so it is
        # shown as itself rather than dropped — visibly odd beats silently gone.
        label = STATUS_LABELS.get(str(r.status), str(r.status).lower())
        sidelined.append({**_player(r), "status": label})
    sidelined.sort(key=lambda p: (p["pos_order"], p["name"]))

    return {
        "active": active,
        "sidelined": sidelined,
        "practice_squad": squad,
    }
