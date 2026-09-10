"""Confirmed ESPN finals fill gaps while nflverse catches up.

The nflverse cache stays untouched. A separate cache preserves confirmed finals
through ESPN outages; every result is matched to the schedule again on each
build, and a published nflverse result always takes precedence.
"""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd

from .nflverse import GameData, SCHEDULE_TZ
from .season import TEAM_ALIASES

SCOREBOARD_URL = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


def _integer(value: object) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError("Expected a nonnegative integer")
    return int(value)


@dataclass(frozen=True)
class FinalResult:
    id: str
    season: int
    kind: str
    week: int
    gameday: str
    away: str
    home: str
    away_score: int
    home_score: int
    overtime: bool


def parse_final(event: dict) -> FinalResult | None:
    """Accept only explicit finals with complete, integral scores."""
    try:
        status = event["status"]["type"]
        if (status.get("completed") is not True or status.get("state") != "post"
                or status.get("name") not in {"STATUS_FINAL", "STATUS_FINAL_OVERTIME"}):
            return None
        season = _integer(event["season"]["year"])
        season_type = _integer(event["season"]["type"])
        week = _integer(event["week"]["number"])
        if season_type == 2 and 1 <= week <= 18:
            kind = "REG"
        elif season_type == 3 and week in {1, 2, 3, 5}:
            kind, week = {1: ("WC", 19), 2: ("DIV", 20), 3: ("CON", 21), 5: ("SB", 22)}[week]
        else:
            return None
        teams = event["competitions"][0]["competitors"]
        home = [t for t in teams if t.get("homeAway") == "home"]
        away = [t for t in teams if t.get("homeAway") == "away"]
        if len(home) != 1 or len(away) != 1 or len(teams) != 2:
            return None
        kick = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
        if kick.tzinfo is None:
            return None
        result = FinalResult(
            id=str(_integer(event["id"])), season=season, kind=kind, week=week,
            gameday=kick.astimezone(SCHEDULE_TZ).date().isoformat(),
            away=TEAM_ALIASES.get(away[0]["team"]["abbreviation"], away[0]["team"]["abbreviation"]),
            home=TEAM_ALIASES.get(home[0]["team"]["abbreviation"], home[0]["team"]["abbreviation"]),
            away_score=_integer(away[0]["score"]), home_score=_integer(home[0]["score"]),
            overtime=_integer(event["status"].get("period", 4)) > 4,
        )
        if result.id == "0" or (result.kind != "REG" and result.away_score == result.home_score):
            return None
        return result
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return None


def _match(result: FinalResult, data: GameData) -> int | None:
    """Require one schedule row, with consistent ID, teams, date, and round."""
    if result.season != data.season:
        return None
    games = data.games
    matches = games[(games["home_team"] == result.home) & (games["away_team"] == result.away)
                    & (games["week"] == result.week) & (games["game_type"] == result.kind)
                    & (games["gameday"] == result.gameday)]
    if len(matches) != 1:
        return None
    row = matches.iloc[0]
    known_id = row.get("espn")
    if pd.notna(known_id) and str(int(known_id)) != result.id:
        return None
    return matches.index[0]


def supplement_results(data: GameData, cache_path: Path, *, offline: bool = False) -> GameData:
    """Use recent confirmed finals for all scoring consumers, once per build."""
    # Cache raw, compact ESPN events so disk input passes the same final-status
    # and score validation as network input. Never persist synthesized wins.
    events: dict[str, dict] = {}
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if cached["version"] == 1 and cached["season"] == data.season:
                for event in cached["events"]:
                    result = parse_final(event)
                    if result is not None:
                        events[result.id] = event
        except (OSError, ValueError, KeyError, TypeError):
            warnings.warn("ESPN finals cache unavailable; using other confirmed results.", stacklevel=2)

    today = data.fetched_at.astimezone(SCHEDULE_TZ).date()
    recent = data.games[(~data.games["played"])
                        & (data.games["gameday"] >= (today - timedelta(days=7)).isoformat())
                        & (data.games["gameday"] <= today.isoformat())]
    if not offline and not recent.empty:
        try:
            start = str(recent["gameday"].min()).replace("-", "")
            response = httpx.get(SCOREBOARD_URL, params={"dates": f"{start}-{today:%Y%m%d}", "limit": 1000},
                                 timeout=10, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload.get("events"), list):
                raise ValueError("Missing ESPN events")
            # Conflicting duplicate event IDs are ambiguous, so neither result
            # should replace a previously confirmed snapshot.
            observed: dict[str, list[dict]] = {}
            for event in payload["events"]:
                result = parse_final(event)
                if result is not None and _match(result, data) is not None:
                    observed.setdefault(result.id, []).append(event)
            for id, candidates in observed.items():
                if len(candidates) == 1:
                    events[id] = candidates[0]
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            warnings.warn("ESPN finals unavailable; retaining previously confirmed results.", stacklevel=2)

    games = data.games.copy()
    applied: list[str] = []
    retained = []
    # More than one ESPN event claiming the same matchup is also ambiguous.
    matched: dict[int, list[tuple[dict, FinalResult]]] = {}
    for event in events.values():
        result = parse_final(event)
        index = _match(result, data)
        if index is not None and not games.at[index, "played"]:
            matched.setdefault(index, []).append((event, result))
    for index, candidates in matched.items():
        if len(candidates) != 1:
            continue
        event, result = candidates[0]
        margin = result.home_score - result.away_score
        for key, value in {"home_score": result.home_score, "away_score": result.away_score,
                           "result": margin, "overtime": int(result.overtime), "played": True,
                           "home_won": margin > 0, "away_won": margin < 0, "is_tie": margin == 0}.items():
            games.at[index, key] = value
        applied.append(str(games.at[index, "game_id"]))
        retained.append({"id": event["id"], "season": event["season"], "week": event["week"],
                         "date": event["date"], "status": event["status"], "competitions": [{
                             "competitors": [{"homeAway": t["homeAway"], "score": t["score"],
                                              "team": {"abbreviation": t["team"]["abbreviation"]}}
                                             for t in event["competitions"][0]["competitors"]]}]})

    if not offline and (retained or cache_path.exists()):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        partial = cache_path.with_suffix(".partial")
        partial.write_text(json.dumps({"version": 1, "season": data.season, "events": retained}, indent=2) + "\n")
        partial.replace(cache_path)
    return replace(data, games=games, espn_finals=tuple(applied))
