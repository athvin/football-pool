"""NFL schedule and results, from the nflverse published CSV.

One HTTPS GET of a single file gives every game from 1999 through the current
season, with scores filled in as they go final. Upstream (Lee Sharpe's nfldata)
commits every 15-90 minutes year round and lands within minutes of a game
ending, so a once-a-day build always has the previous night's finals.

Deliberately does not depend on ``nflreadpy``: it would add six transitive
dependencies and a pre-1.0 API with no retry logic to fetch the same bytes.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
import pandas as pd

from .season import TEAM_ALIASES

GAMES_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
)

# Everything the pool needs; the upstream file has 46 columns.
COLUMNS = [
    "game_id",
    "season",
    "game_type",
    "week",
    "gameday",
    "gametime",
    "away_team",
    "away_score",
    "home_team",
    "home_score",
    "result",
    "overtime",
    "location",
]

# Playoff rounds, in bracket order. These rows do not exist until the bracket is
# actually set — during the regular season the file has only REG rows.
PLAYOFF_ROUNDS = ("WC", "DIV", "CON", "SB")

# How long after kickoff a game may still be missing a result before it counts
# as evidence the data is behind.
#
# One day is enough for every case that can be measured: the worst run is the
# 19:37 Eastern one on a December Sunday, which is 00:37 UTC Monday with the
# night game still in progress, and a single day of grace already reads zero
# there. Two is chosen anyway, to cover what cannot be measured from a fixture —
# a game's date is local to its stadium while fetched_at is UTC, London and
# Munich kickoffs sit a long way from both, and a postponement that upstream has
# not yet re-dated looks exactly like a missing result. The cost is one extra
# day before a stall is noticed; the cost of being wrong the other way is
# refusing to publish a site that was fine.
STALE_GRACE_DAYS = 2

# How many regular-season games may be outstanding before the data is behind by
# a slate rather than by a single late upload. Measured, not guessed: replaying
# a real season a day at a time, the count holds at 0 for four days, sits at 1
# for the next three — the lone Thursday game of the following week — and then
# jumps to 13 once a Sunday has been missed. This sits in that empty band.
STALE_REGULAR_GAMES = 8

# How long after the regular season ends the bracket may still be unpublished.
# nflverse adds the postseason rows once the field is set, which is the night
# week 18 finishes; four days is generous.
BRACKET_GRACE_DAYS = 4


class DataError(Exception):
    """Upstream data was unreachable or did not look like what we expect."""


@dataclass(frozen=True)
class GameData:
    """Season-filtered games plus provenance for the site's freshness display."""

    games: pd.DataFrame
    season: int
    fetched_at: datetime
    upstream_modified: datetime | None
    # "network"  — fetched live, the normal case
    # "cache"    — the committed copy, asked for deliberately with --offline
    # "fallback" — the network was tried and failed, so the committed copy is
    #              standing in. Distinct from "cache" on purpose: one is a
    #              choice and the other is a degraded state, and only the
    #              degraded one should be able to stop a publish.
    source: str

    @property
    def played(self) -> pd.DataFrame:
        return self.games[self.games["played"]]

    @property
    def unplayed(self) -> pd.DataFrame:
        return self.games[~self.games["played"]]

    @property
    def last_completed(self) -> datetime | None:
        """Kickoff date of the most recent completed game."""
        p = self.played
        if p.empty:
            return None
        return pd.to_datetime(p["gameday"]).max().to_pydatetime()

    @property
    def current_week(self) -> int | None:
        """Highest regular-season week with a completed game (None preseason)."""
        reg = self.played[self.played["game_type"] == "REG"]
        return None if reg.empty else int(reg["week"].max())

    @property
    def next_week(self) -> int | None:
        """Lowest regular-season week with games still to play."""
        reg = self.unplayed[self.unplayed["game_type"] == "REG"]
        return None if reg.empty else int(reg["week"].min())

    def overdue(self, kinds: tuple[str, ...] = ("REG",) + PLAYOFF_ROUNDS) -> int:
        """Scheduled games of these kinds whose date has passed with no result.

        Measured against ``fetched_at`` rather than a call to now(), so the
        answer is a property of this object and a test can construct any
        situation it likes.

        A rescheduled game is not counted: nflverse moves ``gameday`` forward
        when a game is postponed, so it stops being in the past.
        """
        pending = self.games[
            ~self.games["played"] & self.games["game_type"].isin(kinds)
        ]
        if pending.empty:
            return 0
        cutoff = pd.Timestamp(self.fetched_at.date()) - pd.Timedelta(days=STALE_GRACE_DAYS)
        return int((pd.to_datetime(pending["gameday"]) < cutoff).sum())

    def staleness_reason(self) -> str | None:
        """Why this data is too far behind to publish, or ``None`` if it is fine.

        Three questions, because no single count answers all of them.

        Counting overdue games calibrates itself beautifully during the regular
        season — zero before week one however old the file is, zero while the
        data is current, a full slate for every week behind — but it can only
        see games it knows about, and **playoff rows do not exist upstream until
        the bracket is set**. A file frozen at the end of week 18 therefore has
        every game it knows of played, and looks perfectly current for the whole
        of January while the entire postseason passes it by. That window is the
        worst possible one to be blind in: the playoff bonuses carry all of the
        bonus scoring, and first and second place routinely swap over them.

        So the postseason gets two extra questions — whether the bracket the
        file does hold has gone stale, and whether it is missing a bracket it
        ought to have by now.
        """
        reg = self.games[self.games["game_type"] == "REG"]

        # 1. The regular season, where a slate is the natural unit. A single
        #    late upload is tolerated; a missed Sunday is not.
        behind = self.overdue(("REG",))
        if behind >= STALE_REGULAR_GAMES:
            return f"{behind} regular-season games have been played but hold no result"

        # 2. The bracket, if we have one. Playoff games are few and are never
        #    postponed, so even one of them sitting past its date without a
        #    result means a whole round has been missed.
        stale_bracket = self.overdue(PLAYOFF_ROUNDS)
        if stale_bracket:
            return f"{stale_bracket} playoff games have been played but hold no result"

        # 3. The bracket we ought to have. Absent rows cannot be counted as
        #    overdue, so this is the only thing that catches a file frozen
        #    between the end of week 18 and the bracket being published.
        if not reg.empty and bool(reg["played"].all()):
            if not self.games["game_type"].isin(PLAYOFF_ROUNDS).any():
                last = pd.to_datetime(reg["gameday"]).max()
                days = (pd.Timestamp(self.fetched_at.date()) - last).days
                if days > BRACKET_GRACE_DAYS:
                    return (
                        f"the regular season ended {days} days ago and the file "
                        f"still holds no playoff games at all"
                    )
        return None


def fetch_games(
    season: int,
    cache_path: Path | None = None,
    *,
    offline: bool = False,
    retries: int = 3,
    timeout: float = 30.0,
) -> GameData:
    """Fetch games for ``season``, falling back to the committed copy.

    The cache is a fallback, never a shortcut: an unreachable upstream degrades
    the site to yesterday's numbers instead of failing the build, but a
    reachable upstream is always preferred. Caching results and serving them
    without a network attempt is the one failure this site must never have.
    """
    raw: bytes | None = None
    upstream_modified: datetime | None = None
    # Initialised to the guarded state, not the exempt one. Every path below
    # reassigns this, so the value is dead today — but "cache" is what waives
    # the staleness check, and a default that waives it means any future path
    # that forgets to set it publishes unguarded while claiming to be a
    # deliberate offline build. Failing closed costs nothing here.
    source = "fallback"

    if not offline:
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                # follow_redirects is required: GitHub release URLs 302 to a CDN
                # host, and httpx does not follow redirects by default.
                resp = httpx.get(
                    GAMES_URL,
                    follow_redirects=True,
                    timeout=timeout,
                    headers={"Accept-Encoding": "gzip"},
                )
                resp.raise_for_status()
                raw = resp.content
                lm = resp.headers.get("last-modified")
                if lm:
                    upstream_modified = parsedate_to_datetime(lm)
                source = "network"
                break
            except Exception as e:  # noqa: BLE001 - retried, then reported
                last_err = e
                if attempt < retries - 1:
                    time.sleep(2**attempt)
        if raw is None and cache_path is None:
            raise DataError(f"could not fetch {GAMES_URL} and no cache available") from last_err

    if raw is None:
        if cache_path is None or not cache_path.exists():
            raise DataError(f"no cached games file at {cache_path}")
        raw = cache_path.read_bytes()
        # Reading the committed copy because it was asked for is a different
        # event from reading it because the network failed, even though the
        # bytes are identical. Only the caller can tell them apart, and only
        # the second one is a reason to refuse to publish.
        source = "cache" if offline else "fallback"

    games = parse_games(raw, season)

    if source == "network" and cache_path is not None:
        # Cache only this season's rows. The upstream file carries every season
        # back to 1999 (~2 MB), and the daily job commits its cache — storing
        # the whole thing would add megabytes of near-identical history to the
        # repository every day for the sake of ~20 KB that changes.
        # Written to a sibling and renamed, because rename is atomic on POSIX
        # and a direct write is not. A run cancelled or killed mid-write would
        # otherwise leave a truncated file that pandas reads back perfectly
        # happily — the columns are all present and the season filter still
        # matches, so nothing raises. Because rows are sorted by week, the part
        # it loses is the most recent one, which is exactly the part that would
        # make the staleness check say everything is fine.
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        partial = cache_path.with_suffix(cache_path.suffix + ".partial")
        games[COLUMNS].to_csv(partial, index=False)
        partial.replace(cache_path)

    return GameData(
        games=games,
        season=season,
        fetched_at=datetime.now(timezone.utc),
        upstream_modified=upstream_modified,
        source=source,
    )


def parse_games(raw: bytes | str | Path, season: int) -> pd.DataFrame:
    """Parse the games CSV, filter to ``season``, and normalize team codes.

    This is the one boundary where upstream codes become pool codes. Everything
    downstream speaks pool codes only.
    """
    if isinstance(raw, Path):
        df = pd.read_csv(raw, usecols=lambda c: c in COLUMNS, low_memory=False)
    else:
        data = raw.encode() if isinstance(raw, str) else raw
        df = pd.read_csv(
            io.BytesIO(data), usecols=lambda c: c in COLUMNS, low_memory=False
        )

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise DataError(
            f"upstream games file is missing expected column(s) {missing} — "
            "the schema changed and the scoring code needs review"
        )

    df = df[df["season"] == season].copy()
    if df.empty:
        raise DataError(f"no games found for season {season}")

    for col in ("home_team", "away_team"):
        df[col] = df[col].replace(TEAM_ALIASES)

    # `result` is the only correct played/unplayed test. Not `home_score > 0`
    # (a 0-score row is not the signal) and not `gameday < today` (games move).
    # Note a tie is result == 0, which is falsy — always test for null, never
    # truthiness.
    df["played"] = df["result"].notna()

    # pandas reads the nullable score columns as float64/NaN, which renders as
    # "24.0" on the page. Int64 (capital I) keeps them integral and nullable.
    for col in ("home_score", "away_score", "week"):
        df[col] = df[col].astype("Int64")

    df["is_tie"] = df["played"] & (df["result"] == 0)
    df["home_won"] = df["played"] & (df["result"] > 0)
    df["away_won"] = df["played"] & (df["result"] < 0)

    return df.sort_values(["week", "gameday", "game_id"]).reset_index(drop=True)


def validate_teams(games: pd.DataFrame, teams: tuple[str, ...]) -> None:
    """Assert the data's team set matches the season config exactly.

    Catches a missing alias, which would otherwise silently drop one team's
    points for the entire season rather than raising.
    """
    seen = set(games["home_team"]) | set(games["away_team"])
    expected = set(teams)
    if seen != expected:
        raise DataError(
            f"team codes in the data do not match rules.yaml. "
            f"In data only: {sorted(seen - expected)}. "
            f"In rules only: {sorted(expected - seen)}. "
            f"A missing entry in TEAM_ALIASES is the usual cause."
        )


def team_records(games: pd.DataFrame, teams: tuple[str, ...]) -> pd.DataFrame:
    """Win/loss/tie record per team from completed regular-season games."""
    rec = pd.DataFrame(
        0, index=list(teams), columns=["w", "l", "t"], dtype=int
    )
    reg = games[games["played"] & (games["game_type"] == "REG")]
    for row in reg.itertuples():
        h, a = row.home_team, row.away_team
        if row.is_tie:
            rec.loc[h, "t"] += 1
            rec.loc[a, "t"] += 1
        elif row.home_won:
            rec.loc[h, "w"] += 1
            rec.loc[a, "l"] += 1
        else:
            rec.loc[a, "w"] += 1
            rec.loc[h, "l"] += 1
    rec["gp"] = rec[["w", "l", "t"]].sum(axis=1)
    rec["win_pct"] = (rec["w"] + 0.5 * rec["t"]) / rec["gp"].where(rec["gp"] > 0)
    return rec.fillna({"win_pct": 0.0})
