"""Live contract checks against the real ESPN API — the server-side half.

ESPN stopped accepting date-range scoreboard queries (dates=YYYYMMDD-YYYYMMDD
began returning 400) and the finals supplement went silently dark: every unit
test stayed green because the feed is stubbed, and ``supplement_results``
downgrades a failed request to a warning by design. This test asks the real
endpoint the exact question a build asks and demands the right answer back,
so the next time ESPN moves, a scheduled run goes red instead of the site
quietly falling back to nflverse lag on a Sunday night.

Skipped unless ESPN_CONTRACT=1: the default suite stays hermetic, and no
deploy is gated on ESPN being up. The espn-contract workflow sets the flag on
a daily in-season schedule. A failure here means "ESPN changed or is down",
not "this repo has a bug" — bring the query and parser in line with reality,
then update the mocked tests in test_espn.py to pin the new shape.

Warnings are promoted to errors on purpose. The production softness — warn
and retain — is exactly what made this class of breakage invisible, and it is
the one behaviour a contract check exists to see through.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import replace
from datetime import timedelta

import pytest

from football_pool.cli import games_cache
from football_pool.espn import supplement_results
from football_pool.nflverse import fetch_games
from football_pool.schedule import kickoff
from football_pool.season import active_season

pytestmark = pytest.mark.skipif(
    not os.environ.get("ESPN_CONTRACT"),
    reason="live ESPN contract check; set ESPN_CONTRACT=1 to run",
)


def test_a_committed_final_can_be_re_derived_from_espn_alone(tmp_path):
    """Blank the season's most recent finals, then win them back from ESPN.

    This exercises the whole production path — the per-day query shape, the
    final-status parsing, and the schedule matching — against the committed
    results as ground truth. If ESPN changes its query grammar or response
    shape again, the scores cannot come back, and this fails.
    """
    year = active_season()
    data = fetch_games(year, cache_path=games_cache(year), offline=True)
    played = data.games[data.games["played"]]
    if played.empty:
        pytest.skip(f"season {year} has no completed games yet; nothing to re-derive")

    last_day = str(played["gameday"].max())
    target = played[played["gameday"] == last_day]
    blanked = data.games.copy()
    blanked.loc[target.index, ["played", "home_won", "away_won", "is_tie"]] = False
    blanked.loc[target.index, ["home_score", "away_score", "result"]] = float("nan")

    # Fetched "the morning after", so the supplement's seven-day lookback
    # asks about exactly the day whose finals were blanked.
    fetched = kickoff(last_day, "13:00") + timedelta(days=1)
    pending = replace(data, games=blanked, fetched_at=fetched)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = supplement_results(pending, tmp_path / "finals.json")

    recovered = out.games.loc[target.index]
    assert set(out.espn_finals) == set(target["game_id"].astype(str))
    for index, expected in target.iterrows():
        actual = recovered.loc[index]
        assert bool(actual["played"]), f"{expected['game_id']} did not come back final"
        assert int(actual["home_score"]) == int(expected["home_score"])
        assert int(actual["away_score"]) == int(expected["away_score"])
        assert bool(actual["home_won"]) == bool(expected["home_won"])
        assert bool(actual["away_won"]) == bool(expected["away_won"])
