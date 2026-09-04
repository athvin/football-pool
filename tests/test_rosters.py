"""The roster layer: fetching, parsing, and its deliberate refusal to fail.

The mirror image of test_nflverse.py's posture. Results are load-bearing and
their tests prove the build *stops* on bad data; a roster is context, so these
prove the build *cannot* stop on it — every failure mode lands on None, which
renders as a team page without a roster section.

No test here touches the network — the transport is stubbed throughout.
"""

from __future__ import annotations

import pytest

from football_pool.rosters import (
    RosterData,
    fetch_roster,
    parse_roster,
    team_roster,
)

from helpers import mkroster_csv


class FakeResponse:
    def __init__(self, content: bytes, status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def roster_bytes():
    """A tiny two-team roster exercising every status bucket and both aliases."""
    return mkroster_csv(
        [
            {"team": "KC", "name": "Starter QB", "pos": "QB", "jersey": 15, "pfr": "MahoPa00"},
            {"team": "KC", "name": "Blind Side", "pos": "OL", "jersey": 76},
            {"team": "KC", "name": "Ballhawk", "pos": "DB", "jersey": 21},
            {"team": "KC", "name": "Hurt Guy", "pos": "WR", "status": "RES"},
            {"team": "KC", "name": "Camp Leg", "pos": "K", "status": "DEV", "years": 0},
            {"team": "KC", "name": "Gone Guy", "pos": "RB", "status": "CUT"},
            # The two clubs the roster file spells differently from the games
            # file — the codes the pool speaks are ARI and LAR.
            {"team": "AZ", "name": "Desert Bird", "pos": "WR"},
            {"team": "LA", "name": "Horns Guy", "pos": "TE"},
        ]
    )


# -- parsing ----------------------------------------------------------------
def test_parses_and_normalizes_team_codes(roster_bytes):
    df = parse_roster(roster_bytes, 2025)
    teams = set(df["team"])
    assert "ARI" in teams and "LAR" in teams
    assert "AZ" not in teams and "LA" not in teams


def test_ex_players_are_dropped_at_the_boundary(roster_bytes):
    """A "roster" listing everyone ever cut would name more ex-players than
    players by December, so the gone are removed where the codes are fixed."""
    df = parse_roster(roster_bytes, 2025)
    assert "Gone Guy" not in set(df["full_name"])
    assert "Hurt Guy" in set(df["full_name"])  # injured reserve is still on the team


def test_jersey_numbers_are_nullable_integers(roster_bytes):
    """float64 renders as "15.0" on the page; Int64 keeps 15 a 15."""
    df = parse_roster(roster_bytes, 2025)
    assert str(df["jersey_number"].dtype) == "Int64"


def test_missing_season_raises(roster_bytes):
    with pytest.raises(Exception, match="no players"):
        parse_roster(roster_bytes, 1999)


def test_schema_change_raises_here_not_downstream(roster_bytes):
    """parse_roster is allowed to raise — fetch_roster is what swallows it.
    Splitting the two keeps the parser honest and the fetch unbreakable."""
    broken = roster_bytes.decode().replace("full_name", "player_name").encode()
    with pytest.raises(Exception, match="missing expected column"):
        parse_roster(broken, 2025)


# -- shaping ----------------------------------------------------------------
def test_team_roster_buckets_by_fate(roster_bytes):
    shaped = team_roster(parse_roster(roster_bytes, 2025), "KC")

    assert [p["name"] for p in shaped["active"]] == [
        "Starter QB",  # field order: QB before OL before DB
        "Blind Side",
        "Ballhawk",
    ]
    assert [(p["name"], p["status"]) for p in shaped["sidelined"]] == [
        ("Hurt Guy", "injured reserve")
    ]
    assert [p["name"] for p in shaped["practice_squad"]] == ["Camp Leg"]


def test_an_unknown_status_is_shown_not_dropped(roster_bytes):
    """A new list upstream still names a real player on a real roster —
    visibly odd beats silently gone."""
    weird = mkroster_csv([{"team": "KC", "name": "Odd Duck", "status": "XYZ"}])
    shaped = team_roster(parse_roster(weird, 2025), "KC")
    assert shaped["sidelined"][0]["status"] == "xyz"


def test_a_team_with_nobody_is_none(roster_bytes):
    """Renders the same as no roster data at all: a page without the section."""
    assert team_roster(parse_roster(roster_bytes, 2025), "SEA") is None


def test_pfr_ids_become_links_and_their_absence_becomes_text(roster_bytes):
    shaped = team_roster(parse_roster(roster_bytes, 2025), "KC")
    by_name = {p["name"]: p for p in shaped["active"]}
    assert by_name["Starter QB"]["pfr_url"] == (
        "https://www.pro-football-reference.com/players/M/MahoPa00.htm"
    )
    assert by_name["Blind Side"]["pfr_url"] is None


def test_a_rookie_is_zero_years_not_missing(roster_bytes):
    shaped = team_roster(parse_roster(roster_bytes, 2025), "KC")
    assert shaped["practice_squad"][0]["years"] == 0


# -- fetching: every road leads somewhere, none leads to an exception --------
def test_fetch_writes_the_cache_and_reports_network(monkeypatch, tmp_path, roster_bytes):
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(roster_bytes))
    cache = tmp_path / "nested" / "roster.csv"

    rd = fetch_roster(2025, cache_path=cache)

    assert isinstance(rd, RosterData)
    assert rd.source == "network"
    assert cache.exists()
    assert not list(cache.parent.glob("*.partial")), "temp file left behind"
    # The cache holds parsed, normalized rows — reading it back is a no-op.
    assert set(parse_roster(cache, 2025)["team"]) >= {"KC", "ARI", "LAR"}


def test_fetch_falls_back_to_cache_when_upstream_is_down(monkeypatch, tmp_path, roster_bytes):
    cache = tmp_path / "roster.csv"
    cache.write_bytes(roster_bytes)

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("httpx.get", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)

    rd = fetch_roster(2025, cache_path=cache)
    assert rd is not None and rd.source == "fallback"
    assert "Starter QB" in set(rd.players["full_name"])


def test_the_season_not_existing_yet_is_none_not_an_error(monkeypatch, tmp_path):
    """The real spring: upstream 404s roster_<year>.csv until the league year
    opens. That must read as "no roster yet", never as a failed build."""
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(b"Not Found", 404))
    monkeypatch.setattr("time.sleep", lambda s: None)

    assert fetch_roster(2027, cache_path=tmp_path / "roster.csv") is None


def test_unparseable_upstream_degrades_to_the_cache(monkeypatch, tmp_path, roster_bytes):
    """A 200 carrying garbage must not beat a good cache — the same lesson the
    games cache learned, held to here with a warning instead of a refusal."""
    cache = tmp_path / "roster.csv"
    cache.write_bytes(roster_bytes)
    good = cache.read_bytes()

    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(b"<html>oops</html>"))

    with pytest.warns(RuntimeWarning, match="roster upstream unusable"):
        rd = fetch_roster(2025, cache_path=cache)

    assert rd is not None and rd.source == "fallback"
    assert cache.read_bytes() == good, "a good cache must not be overwritten"


def test_offline_skips_the_network_and_reads_the_cache(monkeypatch, tmp_path, roster_bytes):
    cache = tmp_path / "roster.csv"
    cache.write_bytes(roster_bytes)
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: pytest.fail("offline must not hit the network")
    )

    rd = fetch_roster(2025, cache_path=cache, offline=True)
    assert rd is not None and rd.source == "cache"


def test_nothing_anywhere_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse(b"", 500))
    monkeypatch.setattr("time.sleep", lambda s: None)

    assert fetch_roster(2025, cache_path=tmp_path / "missing.csv") is None
    assert fetch_roster(2025, cache_path=None) is None
