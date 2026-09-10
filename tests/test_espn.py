"""Only matched, confirmed finals can change the rebuilt standings."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import warnings
from pathlib import Path

import httpx
import pandas as pd
import pytest

from football_pool import espn
from football_pool.nflverse import GameData
from football_pool.schedule import kickoff
from football_pool.scoring import entrant_scores, score_teams

NOW = datetime(2025, 9, 5, 4, tzinfo=timezone.utc)


@pytest.fixture
def pending(games_2025):
    games = games_2025[games_2025.game_type == "REG"].copy()
    games[["played", "home_won", "away_won", "is_tie"]] = False
    games[["home_score", "away_score"]] = pd.NA
    games["result"] = float("nan")
    return GameData(games, 2025, NOW, None, "network")


def final(data, **changes):
    row = data.games.iloc[0]
    return {"id": "401000001", "date": kickoff(row.gameday, row.gametime).isoformat(),
            "season": {"year": data.season, "type": 2}, "week": {"number": int(row.week)},
            "status": {"period": 4, "type": {"state": "post", "completed": True, "name": "STATUS_FINAL"}},
            "competitions": [{"competitors": [
                {"homeAway": "away", "team": {"abbreviation": row.away_team}, "score": "20"},
                {"homeAway": "home", "team": {"abbreviation": row.home_team}, "score": "27"},
            ]}], **changes}


def feed(monkeypatch, events):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"events": events}, request=httpx.Request("GET", url))

    monkeypatch.setattr(espn.httpx, "get", get)
    return calls


def test_final_updates_scores_records_and_pool_totals_once(pending, make_season, monkeypatch, tmp_path):
    event = final(pending)
    row = pending.games.iloc[0]
    pool = make_season([{"name": "Winner", "teams": [row.home_team, "SEA", "KC", "NE"]}], year=2025)
    calls = feed(monkeypatch, [event])
    cache = tmp_path / "espn-finals.json"
    updated = espn.supplement_results(pending, cache)
    actual = updated.games.iloc[0]
    assert actual.played and actual.home_won and not actual.away_won and not actual.is_tie
    assert (actual.home_score, actual.away_score, actual.result) == (27, 20, 7)
    assert updated.espn_finals == (row.game_id,)
    assert updated.current_week == updated.next_week == 1
    assert pending.games.played.sum() == 0
    assert entrant_scores(pool, score_teams(pool, updated.games)).iloc[0].total == pool.lf_of(row.home_team)
    again = espn.supplement_results(pending, cache)
    pd.testing.assert_frame_equal(again.games, updated.games)
    assert len(calls) == 2 and calls[0][1]["params"]["dates"] == "20250904-20250905"
    assert json.loads(cache.read_text())["events"][0]["id"] == event["id"]
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("change", [
    lambda e: e["status"]["type"].update(state="in", completed=False),
    lambda e: e["status"]["type"].update(name="STATUS_SUSPENDED"),
    lambda e: e["status"]["type"].update(completed="true"),
    lambda e: e["season"].update(type=1),
    lambda e: e["week"].update(number=0),
    lambda e: e.update(id="bad"),
    lambda e: e.update(id="0"),
    lambda e: e.update(date="2025-09-04T20:20"),
    lambda e: e["competitions"][0]["competitors"].pop(),
    lambda e: e["competitions"][0]["competitors"][0].update(homeAway="home"),
    lambda e: e["competitions"][0]["competitors"][0].update(score=None),
    lambda e: e["competitions"][0]["competitors"][0].update(score=-1),
    lambda e: e["competitions"][0]["competitors"][0].update(score=True),
    lambda e: e["competitions"][0]["competitors"][0].update(score="20.5"),
])
def test_unconfirmed_or_malformed_results_never_score(pending, monkeypatch, tmp_path, change):
    event = final(pending); change(event)
    feed(monkeypatch, [event, {}, None])
    result = espn.supplement_results(pending, tmp_path / "finals.json")
    assert result.games.played.sum() == 0
    assert not result.espn_finals


@pytest.mark.parametrize("changes", [
    {"season": {"year": 2024, "type": 2}}, {"week": {"number": 2}},
    {"date": "2025-09-06T00:20Z"},
    {"season": {"year": 2025, "type": 3}},
])
def test_wrong_season_week_date_or_round_never_matches(pending, monkeypatch, tmp_path, changes):
    feed(monkeypatch, [final(pending, **changes)])
    assert not espn.supplement_results(pending, tmp_path / "finals.json").espn_finals


def test_wrong_team_conflicting_id_and_duplicate_schedule_are_rejected(pending, monkeypatch, tmp_path):
    cache = tmp_path / "finals.json"
    event = final(pending)
    event["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "XXX"
    feed(monkeypatch, [event])
    assert not espn.supplement_results(pending, cache).espn_finals
    feed(monkeypatch, [final(pending)])
    pending.games["espn"] = 999
    assert not espn.supplement_results(pending, cache).espn_finals
    pending.games["espn"] = 401000001
    assert espn.supplement_results(pending, cache).espn_finals
    duplicated = replace(pending, games=pd.concat([pending.games, pending.games.iloc[:1]], ignore_index=True))
    assert not espn.supplement_results(duplicated, cache).espn_finals


def test_ambiguous_espn_events_do_not_choose_a_winner(pending, monkeypatch, tmp_path):
    event = final(pending)
    duplicate = deepcopy(event)
    duplicate["competitions"][0]["competitors"][1]["score"] = "10"
    feed(monkeypatch, [event, duplicate])
    assert not espn.supplement_results(pending, tmp_path / "finals.json").espn_finals
    duplicate["id"] = "401000002"
    feed(monkeypatch, [event, duplicate])
    assert not espn.supplement_results(pending, tmp_path / "finals.json").espn_finals


def test_shutouts_ties_and_playoff_rounds(pending):
    event = final(pending)
    event["competitions"][0]["competitors"][0]["score"] = "0"
    assert espn.parse_final(event).away_score == 0
    event["competitions"][0]["competitors"][1]["score"] = "0"
    assert espn.parse_final(event).home_score == 0
    event["season"]["type"] = 3
    assert espn.parse_final(event) is None
    event["competitions"][0]["competitors"][1]["score"] = "3"
    event["status"]["period"] = 5
    for week, kind, normalized in [(1, "WC", 19), (2, "DIV", 20), (3, "CON", 21), (5, "SB", 22)]:
        event["week"]["number"] = week
        parsed = espn.parse_final(event)
        assert (parsed.kind, parsed.week, parsed.overtime) == (kind, normalized, True)


def test_away_wins_and_ties_set_consistent_flags(pending, monkeypatch, tmp_path):
    event = final(pending)
    for home_score in ["0", "20"]:
        event["competitions"][0]["competitors"][1]["score"] = home_score
        feed(monkeypatch, [event])
        row = espn.supplement_results(pending, tmp_path / "finals.json").games.iloc[0]
        assert row.played and not row.home_won
        assert row.away_won == (home_score == "0")
        assert row.is_tie == (home_score == "20")


def test_cached_finals_survive_outages_and_offline_builds(pending, monkeypatch, tmp_path):
    cache = tmp_path / "finals.json"
    feed(monkeypatch, [final(pending)])
    good = espn.supplement_results(pending, cache)
    content = cache.read_bytes()
    def fail(*args, **kwargs):
        raise httpx.ConnectError("ESPN unavailable")
    monkeypatch.setattr(espn.httpx, "get", fail)
    with pytest.warns(UserWarning, match="retaining"):
        fallback = espn.supplement_results(pending, cache)
    pd.testing.assert_frame_equal(good.games, fallback.games)
    offline = espn.supplement_results(pending, cache, offline=True)
    pd.testing.assert_frame_equal(good.games, offline.games)
    assert cache.read_bytes() == content
    with pytest.warns(UserWarning):
        empty = espn.supplement_results(pending, tmp_path / "missing.json")
    assert not empty.espn_finals


def test_nflverse_corrections_replace_cached_finals_without_double_counting(pending, monkeypatch, tmp_path):
    cache = tmp_path / "finals.json"
    event = final(pending)
    feed(monkeypatch, [event])
    espn.supplement_results(pending, cache)
    corrected = pending.games.copy()
    index = corrected.index[0]
    for key, value in {"played": True, "home_won": False, "away_won": True,
                       "home_score": 10, "away_score": 20, "result": -10}.items():
        corrected.at[index, key] = value
    result = espn.supplement_results(replace(pending, games=corrected), cache)
    assert not result.espn_finals
    assert result.games.iloc[0].home_score == 10
    assert result.games.iloc[0].away_won
    assert json.loads(cache.read_text())["events"] == []


@pytest.mark.parametrize("content", ["bad JSON", "null", '{"version":1}', '{"version":2,"season":2025}',
                                     '{"version":1,"season":2024}', '{"version":1,"season":2025,"events":[{}]}'])
def test_bad_or_wrong_season_cache_cannot_score(pending, tmp_path, content):
    cache = tmp_path / "finals.json"; cache.write_text(content)
    with warnings.catch_warnings(action="ignore", category=UserWarning):
        result = espn.supplement_results(pending, cache, offline=True)
    assert not result.espn_finals


def test_missing_events_is_an_outage_and_offseason_skips_requests(pending, monkeypatch, tmp_path):
    monkeypatch.setattr(espn.httpx, "get", lambda *a, **k: httpx.Response(200, json={}, request=httpx.Request("GET", espn.SCOREBOARD_URL)))
    with pytest.warns(UserWarning, match="unavailable"):
        assert not espn.supplement_results(pending, tmp_path / "finals.json").espn_finals
    def unexpected(*args, **kwargs):
        raise AssertionError("No request before the season")
    monkeypatch.setattr(espn.httpx, "get", unexpected)
    august = replace(pending, fetched_at=datetime(2025, 8, 1, tzinfo=timezone.utc))
    assert not espn.supplement_results(august, tmp_path / "finals.json").espn_finals


def test_captured_seattle_opener_is_a_confirmed_regular_season_final():
    payload = json.loads((Path(__file__).parent / "fixtures" / "espn_final_scoreboard.json").read_text())
    result = espn.parse_final(payload["events"][0])
    assert (result.season, result.kind, result.week, result.gameday) == (2026, "REG", 1, "2026-09-09")
    assert (result.away, result.away_score, result.home, result.home_score) == ("NE", 10, "SEA", 13)


def test_one_espn_final_rebuilds_standings_and_live_baseline_for_a_partial_week(pending, make_season, monkeypatch, tmp_path):
    from football_pool.render import render_site

    row = pending.games.iloc[0]
    pool = make_season([
        {"name": "Alex", "teams": [row.home_team, "SEA", "KC", "NE"]},
        {"name": "Blair", "teams": [row.home_team, "CIN", "TEN", "NO"]},
        {"name": "Cam", "teams": [row.away_team, "BUF", "ATL", "HOU"]},
    ], year=2025)
    feed(monkeypatch, [final(pending)])
    updated = espn.supplement_results(pending, tmp_path / "finals.json")
    site = tmp_path / "site"
    render_site(pool, updated, site, base="/football-pool/friends", site_base="/football-pool", simulations=20)
    payload = json.loads((site / "data/standings.json").read_text())
    state = payload["state"]
    assert (state["progress"]["played"], state["progress"]["total"], state["progress"]["status"]) == (1, 16, "in progress")
    assert {e["name"] for e in state["leaders"]} == {"Alex", "Blair"}
    entrants = {e["name"]: e for e in payload["entrants"]}
    assert entrants["Alex"]["rank"] == entrants["Blair"]["rank"] == 1
    assert entrants["Cam"]["rank"] == 3
    for name in ["Alex", "Blair"]:
        assert entrants[name]["banked"] == entrants[name]["week_points"] == pool.lf_of(row.home_team)
        assert entrants[name]["week_games_left"] == 3
    assert entrants["Cam"]["banked"] == 0
    html = (site / "index.html").read_text()
    assert "1 of 16 games final" in html and "15 awaiting results" in html
    assert "2 tied for the lead" in html and "Week 1 in progress" in html
    assert "Through week 1" not in html
    assert 'href="/football-pool/friends/schedule/#week-1"' in html
    assert 'href="/football-pool/friends/entrant/alex/"' in html
    assert "Final · ESPN" in html and "1 ESPN-confirmed final" in html
    assert payload["generated"]["espn_finals"] == [row.game_id]
    live = json.loads((site / "data/live.json").read_text())
    match = next(g for g in live["games"] if g["id"] == row.game_id)
    assert match["scored"] is True and match["points"] == {}
    assert (match["homeScore"], match["awayScore"]) == (27, 20)
    assert next(e for e in live["entrants"] if e["name"] == "Alex")["banked"] == pool.lf_of(row.home_team)


def test_before_first_final_is_awaiting_results_and_completed_week_is_labeled_complete(pending, season, games_2025, tmp_path):
    from football_pool.render import render_site

    site = tmp_path / "site"
    render_site(season, pending, site, simulations=20)
    html = (site / "index.html").read_text()
    assert "Week 1 awaiting results" in html and "0 of 16 games final" in html
    assert "Nothing has kicked off yet" not in html
    assert "All entries tied" not in html  # The fixture has a single entrant.
    # Known future scores in the fixture must never leak through unplayed rows.
    assert "Latest finals included" not in html
    week_done = games_2025[games_2025.game_type == "REG"].copy()
    week_done.loc[week_done.week > 1, "played"] = False
    render_site(season, replace(pending, games=week_done), site, simulations=20)
    html = (site / "index.html").read_text()
    assert "Week 1 complete" in html and "16 of 16 games final" in html
    assert "remaining games can change" not in html
