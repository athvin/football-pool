"""The slate: when each week owns the page, and what each game is worth.

Nothing here reads a clock. Every time-dependent function takes the instant as
an argument — the same discipline ``GameData.days_behind`` follows — so a test
can put itself at 23:44 on a Monday night in November without patching
anything.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from football_pool import scoring
from football_pool.schedule import (
    GAME_TAIL,
    WeekWindow,
    default_week,
    entrant_stake,
    game_swing,
    kickoff,
    side_points,
    week_label,
    week_window,
    week_windows,
)

from helpers import mkgames

FIELD = [
    {"name": "Ann", "teams": ["KC", "BAL", "DAL", "CIN"]},
    {"name": "Bob", "teams": ["DET", "BUF", "SF", "NE"]},
    {"name": "Cal", "teams": ["TB", "BUF", "CHI", "BAL"]},
]


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# --- kickoffs -------------------------------------------------------------

def test_kickoff_reads_the_schedule_in_eastern_not_utc():
    # 8:20pm Eastern on 9 September is 00:20 UTC the *next* day. Reading the
    # pair as UTC would put this game on the wrong side of the day boundary.
    assert kickoff("2026-09-09", "20:20") == utc("2026-09-10T00:20:00")


def test_kickoff_follows_the_daylight_saving_switch():
    # September is EDT (UTC-4), January is EST (UTC-5). Same wall clock, one
    # hour apart in absolute terms — which is why the offset cannot be hardcoded.
    september = kickoff("2026-09-13", "13:00")
    january = kickoff("2027-01-10", "13:00")
    assert september.hour == 17
    assert january.hour == 18


def test_a_london_kickoff_keeps_the_sunday_it_is_watched_on():
    # nflverse dates the 09:30 London games by their US Eastern calendar date.
    assert kickoff("2026-10-04", "09:30") == utc("2026-10-04T13:30:00")


@pytest.mark.parametrize("missing", [None, "", float("nan")])
def test_a_missing_kickoff_time_falls_back_to_the_end_of_the_day(missing):
    # Deliberately the latest possible reading: an unknown time must never let
    # a week roll over early.
    assert kickoff("2026-09-13", missing) == utc("2026-09-14T03:59:00")


# --- week windows ---------------------------------------------------------

def test_week_windows_cover_every_week_in_schedule_order():
    games = mkgames(
        [
            {"home": "KC", "away": "BAL", "week": 2, "gameday": "2026-09-17"},
            {"home": "SF", "away": "DAL", "week": 1, "gameday": "2026-09-10"},
            {"home": "TB", "away": "CHI", "week": 3, "gameday": "2026-09-24"},
        ]
    )
    assert [w.week for w in week_windows(games)] == [1, 2, 3]


def test_a_week_closes_one_game_after_its_last_kickoff():
    games = mkgames(
        [
            {"home": "KC", "away": "BAL", "week": 1, "gameday": "2026-09-10", "gametime": "20:15"},
            {"home": "SF", "away": "DAL", "week": 1, "gameday": "2026-09-13", "gametime": "13:00"},
        ]
    )
    (window,) = week_windows(games)
    assert window.opens == kickoff("2026-09-10", "20:15")
    assert window.closes == kickoff("2026-09-13", "13:00") + GAME_TAIL


def test_a_week_never_closes_after_the_next_one_opens():
    # A postponed week-1 game dated inside week 2. Without the clamp this week
    # would still own the page while week 2 was being played.
    games = mkgames(
        [
            {"home": "KC", "away": "BAL", "week": 1, "gameday": "2026-09-10", "gametime": "20:15"},
            {"home": "SF", "away": "DAL", "week": 1, "gameday": "2026-09-22", "gametime": "19:00"},
            {"home": "TB", "away": "CHI", "week": 2, "gameday": "2026-09-17", "gametime": "20:15"},
        ]
    )
    first, second = week_windows(games)
    assert first.closes == second.opens
    assert first.closes < first.opens + timedelta(days=14)


def test_windows_partition_a_real_season(games_2025):
    windows = week_windows(games_2025)
    assert len(windows) == 22
    assert [w.week for w in windows] == list(range(1, 23))
    for earlier, later in zip(windows, windows[1:]):
        assert earlier.closes <= later.opens


def test_windows_of_an_empty_schedule_are_empty():
    assert week_windows(mkgames([])) == []


# --- which week owns the page --------------------------------------------

def _two_weeks():
    return week_windows(
        mkgames(
            [
                {"home": "KC", "away": "BAL", "week": 1, "gameday": "2026-09-14", "gametime": "20:15"},
                {"home": "SF", "away": "DAL", "week": 2, "gameday": "2026-09-20", "gametime": "13:00"},
            ]
        )
    )


def test_the_default_week_is_the_one_being_played():
    windows = _two_weeks()
    assert default_week(windows, kickoff("2026-09-14", "21:00")) == 1


def test_the_default_week_rolls_over_after_monday_night():
    windows = _two_weeks()
    last = kickoff("2026-09-14", "20:15")
    assert default_week(windows, last + timedelta(hours=3)) == 1
    assert default_week(windows, last + timedelta(hours=4)) == 2


def test_the_preseason_defaults_to_the_first_week():
    assert default_week(_two_weeks(), utc("2026-08-13T12:00:00")) == 1


def test_after_the_season_the_last_week_stays(games_2025):
    # The Super Bowl is the last thing that happened, so it is the thing to show.
    assert default_week(week_windows(games_2025), utc("2026-03-01T12:00:00")) == 22


def test_the_default_week_of_an_empty_schedule_is_nothing():
    assert default_week([], utc("2026-09-14T12:00:00")) is None


def test_the_default_never_lands_on_a_week_that_is_over(games_2025):
    windows = week_windows(games_2025)
    for window in windows[:-1]:
        just_after = window.closes + timedelta(seconds=1)
        assert default_week(windows, just_after) != window.week


# --- what a week is called ------------------------------------------------

def test_regular_season_weeks_are_numbered():
    assert week_label(7, "REG") == "Week 7"


@pytest.mark.parametrize(
    "game_type,expected",
    [("WC", "Wild Card"), ("DIV", "Divisional"), ("CON", "Conference"), ("SB", "Super Bowl")],
)
def test_playoff_weeks_are_named_not_numbered(game_type, expected):
    assert week_label(19, game_type) == expected


def test_the_window_carries_its_own_label():
    assert WeekWindow(19, "WC", utc("2027-01-09T18:00:00"), utc("2027-01-12T04:00:00")).label == (
        "Wild Card"
    )


# --- what a game is worth -------------------------------------------------

def test_a_regular_win_is_worth_the_winners_own_leveling_factor(season):
    assert side_points(season, "REG", "KC") == pytest.approx(season.lf_of("KC"))
    # The side never matters in the regular season.
    assert side_points(season, "REG", "KC", is_home=True) == side_points(season, "REG", "KC")


def test_a_wild_card_host_is_playing_for_nothing(season):
    assert side_points(season, "WC", "KC", is_home=True) == 0.0
    assert side_points(season, "WC", "KC") > 0.0


def test_an_unknown_round_is_worth_nothing_rather_than_guessed(season):
    assert side_points(season, "PRE", "KC") == 0.0


def test_stakes_match_what_scoring_actually_pays(season, games_2025):
    """The anti-drift test.

    The bonus table is now written down in two places — ``scoring`` pays it out
    and ``schedule`` advertises it in advance. If they ever disagree the site
    would promise points it does not award, so tie them together against every
    real playoff result.
    """
    playoffs = games_2025[games_2025["played"] & games_2025["game_type"].isin(["WC", "DIV", "CON", "SB"])]
    assert len(playoffs) == 13

    for row in playoffs.itertuples():
        winner = row.home_team if row.home_won else row.away_team
        one_game = games_2025[games_2025["game_id"] == row.game_id]
        paid = scoring.score_playoffs(season, one_game)[season.idx[winner]]
        promised = side_points(season, row.game_type, winner, is_home=bool(row.home_won))
        assert promised == pytest.approx(paid), row.game_id


# --- swing ----------------------------------------------------------------

def test_swing_is_zero_when_nobody_in_the_pool_is_involved(make_season):
    season = make_season(FIELD)
    assert game_swing(season, "REG", "ARI", "NYJ") == 0.0


def test_swing_is_zero_when_the_whole_pool_holds_one_side(make_season):
    """The test that justifies centring.

    If everyone owns the winner, everyone rises together and the standings do
    not move at all. An uncentred sum would call this the biggest game of the
    week.
    """
    season = make_season(
        [
            {"name": "Ann", "teams": ["KC", "DAL", "CIN", "SEA"]},
            {"name": "Bob", "teams": ["KC", "DET", "SF", "NE"]},
        ]
    )
    assert game_swing(season, "REG", "NYJ", "KC") == 0.0


def test_swing_grows_when_the_pool_is_split(make_season):
    season = make_season(FIELD)
    split = game_swing(season, "REG", "BAL", "BUF")  # Ann+Cal vs Bob+Cal
    lopsided = game_swing(season, "REG", "NYJ", "BAL")  # Ann+Cal vs nobody
    assert split > lopsided > 0.0


def test_swing_counts_both_directions_when_your_two_teams_meet(make_season):
    season = make_season([{"name": "Ann", "teams": ["KC", "BAL", "DAL", "CIN"]}])
    # One entrant on both sides: whatever happens they score, so the pool's
    # order cannot move and the swing is zero.
    assert game_swing(season, "REG", "BAL", "KC") == 0.0


def test_an_empty_field_has_no_swing(season):
    # picks.yaml refuses to load an empty field, so build one directly — the
    # projection layer guards against the same state, and a divide-by-zero here
    # would take the whole page down rather than draw an empty week.
    assert game_swing(replace(season, entrants=()), "REG", "KC", "BAL") == 0.0


# --- what one entrant can take out of a game ------------------------------

def test_holding_neither_side_is_worth_nothing(season):
    assert entrant_stake(season, "REG", "ARI", "NYJ", {"KC"}) == (0.0, 0.0)


def test_holding_one_side_risks_everything(season):
    best, worst = entrant_stake(season, "REG", "KC", "NYJ", {"KC"})
    assert best == pytest.approx(season.lf_of("KC"))
    assert worst == 0.0


def test_holding_both_sides_banks_the_smaller_stake(season):
    best, worst = entrant_stake(season, "REG", "KC", "SEA", {"KC", "SEA"})
    lfs = sorted([season.lf_of("KC"), season.lf_of("SEA")])
    assert (worst, best) == pytest.approx(tuple(lfs))
    # Never their sum — both teams cannot win the same game.
    assert best < sum(lfs)


# --- a week's worth of points --------------------------------------------

def test_the_week_window_ignores_whether_the_games_were_played(season):
    """A finished week still has to report what *was* on the table."""
    slate = mkgames([{"home": "KC", "away": "NYJ", "hs": 30, "as_": 3}])
    assert week_window(season, slate, {"KC"}) == (pytest.approx(season.lf_of("KC")), 0.0)


def test_a_week_with_no_owned_teams_has_nothing_on_the_table(season):
    slate = mkgames([{"home": "ARI", "away": "NYJ"}])
    assert week_window(season, slate, {"KC"}) == (0.0, 0.0)


def test_week_window_agrees_with_next_week_window_on_the_next_week(make_season, games_2025):
    """Guards the refactor: ``potential`` now delegates here."""
    from football_pool.potential import next_week_window

    season = make_season(FIELD)
    teams = set(season.entrants[0].teams)

    # Rewind to a mid-season state so there is a "next week" at all.
    games = games_2025.copy()
    games.loc[games["week"] > 10, "played"] = False

    rem = games[(~games["played"]) & (games["game_type"] == "REG")]
    slate = rem[rem["week"] == int(rem["week"].min())]
    assert week_window(season, slate, teams) == next_week_window(season, games, teams)
