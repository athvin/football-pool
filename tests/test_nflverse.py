"""The data layer: fetching, parsing, normalization, and graceful degradation.

No test here touches the network — the transport is stubbed so the failure
modes (timeout, 500, missing column) are exercised deterministically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from football_pool.nflverse import (
    SCHEDULE_TZ,
    STALE_DAYS_LIMIT,
    DataError,
    GameData,
    fetch_games,
    parse_games,
    team_records,
    validate_teams,
)

FIXTURES = Path(__file__).parent / "fixtures"
CSV_2025 = FIXTURES / "games_2025.csv"


class FakeResponse:
    def __init__(self, content: bytes, status: int = 200, headers: dict | None = None):
        self.content = content
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def csv_bytes():
    return CSV_2025.read_bytes()


@pytest.fixture
def csv_with_lines(csv_bytes):
    """The fixture file plus the market columns upstream carries alongside it.

    The committed fixture predates them, which is useful in itself: everything
    that reads ``csv_bytes`` is asserting that the market is optional, and this
    one asserts what happens when it is there.
    """
    rows = csv_bytes.decode().splitlines()
    header = rows[0] + ",spread_line,total_line,away_moneyline,home_moneyline"
    return "\n".join([header, *(f"{r},-3.5,44.5,140,-165" for r in rows[1:])]).encode()


# -- parsing ----------------------------------------------------------------
def test_parses_the_season_and_flags_played_games(games_2025):
    assert len(games_2025) == 285
    assert games_2025["played"].all()  # 2025 is complete
    assert set(games_2025["game_type"]) == {"REG", "WC", "DIV", "CON", "SB"}


def test_scores_are_integers_not_floats(games_2025):
    """float64 would render as '24.0' on the page."""
    assert str(games_2025["home_score"].dtype) == "Int64"
    assert str(games_2025["away_score"].dtype) == "Int64"


def test_identifies_the_real_tie(games_2025):
    ties = games_2025[games_2025["is_tie"]]
    assert len(ties) == 1
    row = ties.iloc[0]
    assert {row["home_team"], row["away_team"]} == {"GB", "DAL"}
    assert row["home_score"] == row["away_score"] == 40
    # A tie is neither a home nor an away win.
    assert not row["home_won"] and not row["away_won"]


def test_normalizes_upstream_team_codes(games_2025):
    """Upstream says LA; the pool says LAR."""
    seen = set(games_2025["home_team"]) | set(games_2025["away_team"])
    assert "LAR" in seen
    assert "LA" not in seen


def test_unplayed_games_are_not_counted(csv_bytes):
    """Blank result means scheduled, even though blank scores look like 0."""
    doctored = csv_bytes.decode().splitlines()
    header = doctored[0]
    # Blank out the scores and result of one game.
    cols = header.split(",")
    i_hs, i_as, i_res = cols.index("home_score"), cols.index("away_score"), cols.index("result")
    parts = doctored[1].split(",")
    parts[i_hs] = parts[i_as] = parts[i_res] = ""
    doctored[1] = ",".join(parts)

    df = parse_games("\n".join(doctored).encode(), 2025)
    assert int(df["played"].sum()) == 284
    assert not df.iloc[0]["played"]
    assert not df.iloc[0]["is_tie"]  # blank is not a 0-0 tie


def test_missing_season_raises(csv_bytes):
    with pytest.raises(DataError, match="no games found for season"):
        parse_games(csv_bytes, 1998)


def test_schema_change_raises(csv_bytes):
    lines = csv_bytes.decode().splitlines()
    lines[0] = lines[0].replace("result", "outcome")
    with pytest.raises(DataError, match="missing expected column"):
        parse_games("\n".join(lines).encode(), 2025)


def test_accepts_a_path(games_2025):
    assert parse_games(CSV_2025, 2025).equals(games_2025)


# -- the market columns, which are read but never required -------------------
def test_the_market_columns_come_through_when_upstream_has_them(csv_with_lines):
    """The pool was already downloading these every run and dropping them at the
    column filter."""
    df = parse_games(csv_with_lines, 2025)

    assert (df["spread_line"] == -3.5).all()
    assert (df["total_line"] == 44.5).all()


def test_a_file_with_no_market_columns_parses_anyway(games_2025):
    """Results are load-bearing, opinions are not: a file the books never got to
    must still build the site, exactly as it did before the lines were read."""
    assert "spread_line" not in games_2025.columns
    assert len(games_2025) == 285


def test_a_missing_market_column_is_not_a_schema_change(csv_with_lines):
    """The counterpart to ``test_schema_change_raises``. Renaming a scoring
    column stops the build; a line the books have not posted must not, or the
    forecast layer would have quietly become able to take the site down.
    """
    lines = csv_with_lines.decode().splitlines()
    lines[0] = lines[0].replace("spread_line", "closing_spread")

    df = parse_games("\n".join(lines).encode(), 2025)
    assert "spread_line" not in df.columns
    assert "closing_spread" not in df.columns  # not asked for, not carried
    assert (df["total_line"] == 44.5).all()  # the rest still arrives


# -- the coach columns, held to the same optional posture as the market ------
@pytest.fixture
def csv_with_coaches(csv_bytes):
    """The fixture file plus the coach columns upstream carries alongside it."""
    rows = csv_bytes.decode().splitlines()
    header = rows[0] + ",away_coach,home_coach"
    return "\n".join([header, *(f"{r},Road Coach,Home Coach" for r in rows[1:])]).encode()


def test_the_coach_columns_come_through_when_upstream_has_them(csv_with_coaches):
    df = parse_games(csv_with_coaches, 2025)
    assert (df["home_coach"] == "Home Coach").all()
    assert (df["away_coach"] == "Road Coach").all()


def test_a_file_with_no_coach_columns_parses_anyway(games_2025):
    """A coach's name decorates a team page and can never reach a score, so a
    feed that stops carrying it must build the site exactly as before."""
    assert "home_coach" not in games_2025.columns
    assert len(games_2025) == 285


def test_the_cache_keeps_the_coaches_it_was_built_from(
    monkeypatch, tmp_path, csv_with_coaches
):
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(csv_with_coaches))
    cache = tmp_path / "games.csv"

    fetch_games(2025, cache_path=cache)

    assert (parse_games(cache, 2025)["home_coach"] == "Home Coach").all()


# -- validation -------------------------------------------------------------
def test_validate_teams_accepts_a_matching_set(season, games_2025):
    validate_teams(games_2025, season.teams)


def test_validate_teams_reports_a_missing_alias(season, games_2025):
    broken = games_2025.copy()
    broken.loc[broken["home_team"] == "LAR", "home_team"] = "LA"
    with pytest.raises(DataError, match="In data only"):
        validate_teams(broken, season.teams)


# -- records ----------------------------------------------------------------
def test_team_records_count_every_game_once(season, games_2025):
    rec = team_records(games_2025, season.teams)
    assert rec["gp"].sum() == 272 * 2
    assert (rec["gp"] == 17).all()
    assert rec["t"].sum() == 2  # one tie, counted for both teams


def test_win_pct_treats_a_tie_as_half(season, games_2025):
    rec = team_records(games_2025, season.teams)
    gb = rec.loc["GB"]
    assert gb["win_pct"] == pytest.approx((gb["w"] + 0.5 * gb["t"]) / 17)


# -- fetching ---------------------------------------------------------------
def test_fetch_writes_and_reports_provenance(monkeypatch, tmp_path, csv_bytes):
    monkeypatch.setattr(
        "httpx.get",
        lambda *a, **k: FakeResponse(
            csv_bytes, headers={"last-modified": "Wed, 12 Aug 2026 22:16:24 GMT"}
        ),
    )
    cache = tmp_path / "games.csv"
    gd = fetch_games(2025, cache_path=cache)

    assert gd.source == "network"
    assert cache.exists()
    assert gd.upstream_modified == datetime(2026, 8, 12, 22, 16, 24, tzinfo=timezone.utc)
    assert gd.fetched_at.tzinfo is timezone.utc


def test_fetch_falls_back_to_cache_when_upstream_is_down(monkeypatch, tmp_path, csv_bytes):
    """An nflverse outage degrades to the committed copy rather than raising.

    Reported as "fallback", not "cache". The bytes are the same either way, but
    one is a deliberate --offline build and the other is a degraded state, and
    only the degraded one is a reason to refuse to publish. Collapsing them is
    what would let a stale board go live during an outage.
    """
    cache = tmp_path / "games.csv"
    cache.write_bytes(csv_bytes)

    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("connection reset")

    monkeypatch.setattr("httpx.get", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)

    gd = fetch_games(2025, cache_path=cache, retries=3)
    assert gd.source == "fallback"
    assert len(calls) == 3  # retried before giving up


def test_an_explicit_offline_build_is_not_a_fallback(tmp_path, csv_bytes):
    """--offline asks for the committed copy; nothing has gone wrong."""
    cache = tmp_path / "games.csv"
    cache.write_bytes(csv_bytes)

    gd = fetch_games(2025, cache_path=cache, offline=True)
    assert gd.source == "cache"
    assert len(gd.games) == 285


def test_fetch_retries_then_succeeds(monkeypatch, tmp_path, csv_bytes):
    attempts = {"n": 0}

    def flaky(*a, **k):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("timeout")
        return FakeResponse(csv_bytes)

    monkeypatch.setattr("httpx.get", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)

    gd = fetch_games(2025, cache_path=tmp_path / "g.csv")
    assert gd.source == "network"
    assert attempts["n"] == 3


def test_fetch_raises_when_offline_with_no_cache(tmp_path):
    with pytest.raises(DataError, match="no cached games file"):
        fetch_games(2025, cache_path=tmp_path / "absent.csv", offline=True)


def test_offline_skips_the_network(monkeypatch, tmp_path, csv_bytes):
    cache = tmp_path / "games.csv"
    cache.write_bytes(csv_bytes)
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: pytest.fail("offline must not hit the network")
    )
    assert fetch_games(2025, cache_path=cache, offline=True).source == "cache"


def test_fetch_without_cache_or_network_raises(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(b"", 500))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(DataError, match="could not fetch"):
        fetch_games(2025, cache_path=None)


# -- derived views ----------------------------------------------------------
def test_week_helpers_on_a_partial_season(csv_bytes):
    """Mid-season: weeks 1-3 final, the rest still scheduled."""
    lines = csv_bytes.decode().splitlines()
    cols = lines[0].split(",")
    i_week, i_type = cols.index("week"), cols.index("game_type")
    i_hs, i_as, i_res = cols.index("home_score"), cols.index("away_score"), cols.index("result")

    out = [lines[0]]
    for ln in lines[1:]:
        p = ln.split(",")
        if p[i_type] != "REG" or int(p[i_week]) > 3:
            p[i_hs] = p[i_as] = p[i_res] = ""
        out.append(",".join(p))

    df = parse_games("\n".join(out).encode(), 2025)

    class G:
        games = df

    from football_pool.nflverse import GameData

    gd = GameData(df, 2025, datetime.now(timezone.utc), None, "cache")
    assert gd.current_week == 3
    assert gd.next_week == 4
    assert gd.last_completed is not None
    assert len(gd.played) + len(gd.unplayed) == len(df)


def test_week_helpers_before_the_season_starts(games_2025):
    from football_pool.nflverse import GameData

    empty = games_2025.copy()
    empty["played"] = False
    gd = GameData(empty, 2025, datetime.now(timezone.utc), None, "cache")
    assert gd.current_week is None
    assert gd.last_completed is None
    assert gd.next_week == 1


# -- staleness, the one measure that decides whether to publish --------------
def _at(games, when, season=2025, source="fallback"):
    return GameData(games, season, when, None, source)


def _on(games, anchor, days):
    return (pd.Timestamp(anchor) + pd.Timedelta(days=days)).to_pydatetime().replace(
        tzinfo=timezone.utc
    )


def test_a_schedule_with_no_results_is_current_before_the_season(games_2025):
    """August is not staleness. This is what rules out anything clock-based.

    The committed copy can be six months old and still perfectly correct right
    up until week one, because nothing has been played.
    """
    preseason = games_2025.copy()
    preseason["played"] = False
    assert _at(preseason, _on(preseason, preseason["gameday"].min(), -30)).days_behind == 0


def test_a_finished_season_is_never_behind(games_2025):
    """It ran to a played Super Bowl, so there is nothing outstanding."""
    sb = games_2025[games_2025["game_type"] == "SB"]["gameday"].max()
    for days in (1, 30, 200):
        assert _at(games_2025, _on(games_2025, sb, days)).days_behind == 0


def test_fresh_data_is_never_behind(games_2025):
    played = games_2025.copy()
    played.loc[played["week"] > 11, "played"] = False
    played.loc[played["game_type"] != "REG", "played"] = False
    latest = played.loc[played["played"], "gameday"].max()
    for days in (0, 1):
        assert _at(played, _on(played, latest, days)).days_behind < STALE_DAYS_LIMIT


def test_a_missed_slate_is_caught_within_days_not_weeks(games_2025):
    """Detection latency is the whole value of the guard.

    Counting overdue *games* cannot fire until a whole slate is outstanding,
    which is ten days after a Sunday freeze — ten days of publishing a wrong
    leaderboard. Counting days catches the same freeze on the fourth.
    """
    frozen = games_2025.copy()
    sunday = pd.Timestamp("2025-11-16")
    frozen.loc[pd.to_datetime(frozen["gameday"]) > sunday, "played"] = False

    assert _at(frozen, _on(frozen, sunday, 2)).days_behind < STALE_DAYS_LIMIT
    for days in (4, 7, 14):
        assert _at(frozen, _on(frozen, sunday, days)).days_behind >= STALE_DAYS_LIMIT


def test_the_frozen_preseason_file_is_caught(games_2025):
    """The failure this exists for: a copy stuck in August, read in November."""
    frozen = games_2025.copy()
    frozen["played"] = False
    behind = _at(frozen, datetime(2025, 11, 20, tzinfo=timezone.utc)).days_behind
    assert behind > 60


def test_a_file_frozen_before_the_bracket_is_published_is_caught(games_2025):
    """Absent rows cannot be counted as overdue, so they are counted as silence.

    nflverse does not publish postseason rows until the field is set, so a copy
    frozen at the end of week 18 has every game it knows about played and reads
    as perfectly current — for the whole of January, the window that decides
    the money. Nothing outstanding is only trustworthy if the file ran to a
    played Super Bowl.
    """
    no_bracket = games_2025[games_2025["game_type"] == "REG"].copy()
    week18 = no_bracket["gameday"].max()

    assert _at(no_bracket, _on(no_bracket, week18, 1)).days_behind < STALE_DAYS_LIMIT
    for days in (4, 10, 30):
        assert _at(no_bracket, _on(no_bracket, week18, days)).days_behind >= STALE_DAYS_LIMIT


def test_the_fortnight_before_the_super_bowl_is_not_staleness(games_2025):
    """The longest legitimate silence in the calendar must not read as a stall."""
    waiting = games_2025.copy()
    waiting.loc[waiting["game_type"] == "SB", "played"] = False
    con = waiting[waiting["game_type"] == "CON"]["gameday"].max()

    for days in (1, 5, 10, 13):
        assert _at(waiting, _on(waiting, con, days)).days_behind < STALE_DAYS_LIMIT, days


def test_the_measure_reads_the_eastern_clock(games_2025):
    """gameday is a US Eastern calendar date, including the London kickoffs.

    Reading it in UTC would put the day boundary mid-slate: the Sunday sweep
    runs to 23:37 Eastern, so in UTC it is already the next day, and a UTC date
    would call Sunday's just-finished games a day late.
    """
    played = games_2025.copy()
    played.loc[played["week"] > 11, "played"] = False
    played.loc[played["game_type"] != "REG", "played"] = False
    latest = played.loc[played["played"], "gameday"].max()

    # 23:37 Eastern is the following day in UTC in both halves of the season:
    # 04:37 on standard time, 03:37 on daylight time.
    evening_run = (
        pd.Timestamp(latest).tz_localize(SCHEDULE_TZ) + pd.Timedelta(hours=23, minutes=37)
    ).to_pydatetime().astimezone(timezone.utc)
    assert evening_run.date() != pd.Timestamp(latest).date()  # UTC has rolled over
    assert _at(played, evening_run).days_behind == 0


def test_a_good_cache_survives_a_successful_but_empty_response(
    monkeypatch, tmp_path, csv_bytes
):
    """A 200 is not the same as good data.

    A regenerated release asset or a stale CDN object answers perfectly while
    carrying no results at all. Writing that over the committed copy destroys
    the very thing the fallback exists to be — so the cache is only refreshed
    from data that is current.
    """
    lines = csv_bytes.decode().splitlines()
    cols = lines[0].split(",")
    blanks = [cols.index(c) for c in ("home_score", "away_score", "result")]
    wiped = [lines[0]]
    for line in lines[1:]:
        parts = line.split(",")
        for i in blanks:
            parts[i] = ""
        wiped.append(",".join(parts))

    cache = tmp_path / "games.csv"
    cache.write_bytes(csv_bytes)
    good = cache.read_bytes()

    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse("\n".join(wiped).encode()))
    gd = fetch_games(2025, cache_path=cache)

    assert gd.source == "network"  # the fetch genuinely succeeded
    assert gd.days_behind >= STALE_DAYS_LIMIT  # but the data is worthless
    assert cache.read_bytes() == good, "a good cache must not be overwritten"


def test_the_cache_is_written_atomically(monkeypatch, tmp_path, csv_bytes):
    """A killed run must not leave a truncated file behind.

    pandas reads a short CSV back without complaint — every column is present
    and the season filter still matches — and because rows are sorted by week
    the part lost is the most recent, which is exactly what the staleness
    measure depends on to notice anything is wrong.
    """
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(csv_bytes))
    cache = tmp_path / "nested" / "games.csv"

    fetch_games(2025, cache_path=cache)

    assert cache.exists()
    assert not list(cache.parent.glob("*.partial")), "temp file left behind"


def test_the_cache_keeps_the_lines_it_was_built_from(monkeypatch, tmp_path, csv_with_lines):
    """The committed snapshot is a record of what the build saw that day, and
    the lines are the part of it that moves. Dropping them would leave an
    offline rebuild fitting to August while the live one fitted to this week."""
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(csv_with_lines))
    cache = tmp_path / "games.csv"

    fetch_games(2025, cache_path=cache)

    assert (parse_games(cache, 2025)["spread_line"] == -3.5).all()


def test_provenance_defaults_to_the_guarded_state(monkeypatch, tmp_path, csv_bytes):
    """A path that forgets to set the source must not waive the check.

    "cache" is the value that exempts a build, so it is the wrong default: a
    future branch returning GameData without assigning provenance would publish
    unguarded while claiming to be a deliberate offline build.
    """
    import inspect

    from football_pool import nflverse

    source = inspect.getsource(nflverse.fetch_games)
    first = source.index("source = ")
    assert source[first:].startswith('source = "fallback"')

    # And the three real paths still report themselves correctly.
    cache = tmp_path / "games.csv"
    cache.write_bytes(csv_bytes)
    assert fetch_games(2025, cache_path=cache, offline=True).source == "cache"

    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(csv_bytes))
    assert fetch_games(2025, cache_path=tmp_path / "b.csv").source == "network"

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr("httpx.get", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert fetch_games(2025, cache_path=cache).source == "fallback"
