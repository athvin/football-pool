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


# -- staleness, the measure that decides whether to publish -------------------
def _at(games, when, season=2025, source="fallback"):
    return GameData(games, season, when, None, source)


def test_nothing_is_overdue_before_the_season_starts(games_2025):
    """A schedule with no results is not stale in August — it is just August.

    This is the case that rules out anything clock-based: the committed file
    can be months old and still perfectly correct, right up until week one.
    """
    preseason = games_2025.copy()
    preseason["played"] = False
    first = pd.Timestamp(preseason["gameday"].min())
    before = (first - pd.Timedelta(days=30)).to_pydatetime().replace(tzinfo=timezone.utc)

    assert _at(preseason, before).overdue == 0


def test_nothing_is_overdue_once_the_season_has_finished(games_2025):
    """Every game has a result, so there is nothing outstanding to be behind on."""
    after = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert _at(games_2025, after).overdue == 0


def test_fresh_data_is_not_overdue(games_2025):
    """The day after a slate, with those results in, counts nothing against us."""
    played = games_2025.copy()
    played.loc[played["week"] > 11, "played"] = False
    played.loc[played["game_type"] != "REG", "played"] = False
    latest = pd.Timestamp(played.loc[played["played"], "gameday"].max())
    next_day = (latest + pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=timezone.utc)

    assert _at(played, next_day).overdue == 0


def test_a_late_result_is_tolerated_but_a_missed_slate_is_not(games_2025):
    """The signal has to distinguish a slow upload from a week gone missing.

    Replayed a day at a time, the count holds at 0 through the grace window,
    sits at 1 for the lone Thursday game of the next week, then jumps to a full
    slate. STALE_GAME_LIMIT sits in that empty band.
    """
    from football_pool.cli import STALE_GAME_LIMIT

    played = games_2025.copy()
    played.loc[played["week"] > 11, "played"] = False
    played.loc[played["game_type"] != "REG", "played"] = False
    latest = pd.Timestamp(played.loc[played["played"], "gameday"].max())
    day_after = (latest + pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=timezone.utc)

    def overdue_after(days):
        return _at(played, day_after + pd.Timedelta(days=days)).overdue

    # A few days late: still under the limit, so the site publishes.
    assert overdue_after(3) < STALE_GAME_LIMIT
    assert overdue_after(6) < STALE_GAME_LIMIT
    # A whole slate missed: over the limit, so the site refuses.
    assert overdue_after(10) >= STALE_GAME_LIMIT
    assert overdue_after(14) >= STALE_GAME_LIMIT


def test_the_frozen_preseason_file_is_caught_loudly(games_2025):
    """The actual failure this exists for.

    Branch protection stopped the daily job refreshing the committed copy, so
    it sits at preseason. Consulted in November it would publish an all-zeros
    leaderboard over a correct one.
    """
    from football_pool.cli import STALE_GAME_LIMIT

    frozen = games_2025.copy()
    frozen["played"] = False
    november = datetime(2025, 11, 20, tzinfo=timezone.utc)

    assert _at(frozen, november).overdue > 100
    assert _at(frozen, november).overdue >= STALE_GAME_LIMIT


def test_playoff_games_do_not_count_toward_staleness(games_2025):
    """Bracket rows only exist once seeded, so they cannot measure lateness."""
    reg_only = games_2025.copy()
    reg_only["played"] = False
    late = datetime(2026, 3, 1, tzinfo=timezone.utc)

    total = _at(reg_only, late).overdue
    assert total == int((reg_only["game_type"] == "REG").sum())
