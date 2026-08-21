"""The January bracket.

A bracket is a fixed shape filled in over five weeks, so these tests are mostly
about what it says when it does *not* know something — which is the state it
spends eleven months of the year in.
"""

from __future__ import annotations

import pytest

from football_pool import bracket
from football_pool.standings import playoff_seeds


@pytest.fixture
def season(make_season):
    return make_season(
        [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}], year=2025
    )


@pytest.fixture
def preseason(games_2025):
    """August: a regular-season slate and nothing played.

    The postseason rows are dropped rather than merely blanked, because that is
    what a real feed looks like in August — the league does not publish a
    wild-card fixture before it knows who is in it.
    """
    g = games_2025[games_2025["game_type"] == "REG"].copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    return g


def _round(built, code):
    return next(r for r in built if r["round"] == code)


def test_the_shape_is_the_same_whatever_is_known(season, games_2025, preseason):
    """Fourteen teams, thirteen games: three, two, one a conference, then one.

    Drawn identically in August and in February. A bracket that grows rounds as
    they happen would reflow the page under whoever is reading it.
    """
    for games in (preseason, games_2025):
        built = bracket.build(season, games, playoff_seeds(season, games))
        counts = {r["round"]: len(r["games"]) for r in built}
        assert counts == {"WC": 6, "DIV": 4, "CON": 2, "SB": 1}
        assert [r["label"] for r in built] == [
            "Wild Card", "Divisional", "Conference", "Super Bowl",
        ]


def test_before_a_kickoff_the_bracket_is_honestly_empty(season, preseason):
    """No game played means no seeds, and no seeds means no teams.

    playoff_seeds refuses to guess from an 0-0 league, because its tiebreaker
    ladder falls through to alphabetical and produces a confident-looking field
    with Arizona as a one seed. The bracket inherits that refusal rather than
    working around it.
    """
    built = bracket.build(season, preseason, playoff_seeds(season, preseason))

    for round_ in built:
        for tie in round_["games"]:
            assert tie.home.team is None
            assert tie.away.team is None
            assert not tie.known

    # The shape still says what each slot is waiting for.
    labels = {s.label for tie in _round(built, "WC")["games"] for s in (tie.home, tie.away)}
    assert labels == {"2 seed", "3 seed", "4 seed", "5 seed", "6 seed", "7 seed"}
    assert [b["team"] for b in bracket.byes(season, {})] == [None, None]


def test_the_wild_card_round_is_drawn_from_the_seeds(season, games_2025):
    """2 v 7, 3 v 6, 4 v 5 — the one part of the bracket seeds fully determine.

    Asserted against a *mid-season* projection rather than the finished season,
    because that is the state where the pairings are being read off a
    projection and the round has not been played.
    """
    partial = games_2025.copy()
    partial.loc[partial["week"] > 10, "played"] = False
    partial = partial[partial["game_type"] == "REG"]
    seeds = playoff_seeds(season, partial)
    assert seeds, "ten weeks in, the standings can seed a field"

    built = bracket.build(season, partial, seeds)
    for tie in _round(built, "WC")["games"]:
        assert (tie.home.seed, tie.away.seed) in bracket.WILD_CARD_PAIRS
        assert tie.known
        # And the seeded team is the one the standings put there.
        assert seeds[tie.home.team] == tie.home.seed
        assert season.conf_of[tie.home.team] == tie.conference
        assert season.conf_of[tie.away.team] == tie.conference
        assert not tie.played


def test_the_one_seed_is_named_rather_than_left_out(season, games_2025):
    """"Why is my team not in the wild-card round" has one good answer."""
    partial = games_2025[games_2025["game_type"] == "REG"]
    seeds = playoff_seeds(season, partial)
    resting = bracket.byes(season, seeds)

    assert [b["conference"] for b in resting] == ["AFC", "NFC"]
    for b in resting:
        assert seeds[b["team"]] == 1
        assert season.conf_of[b["team"]] == b["conference"]
    # And nobody on a bye is in a wild-card game.
    playing = {
        side.team
        for tie in _round(bracket.build(season, partial, seeds), "WC")["games"]
        for side in (tie.home, tie.away)
    }
    assert not playing & {b["team"] for b in resting}


def test_rounds_past_the_first_say_where_their_teams_come_from(season, games_2025):
    """Because reseeding means they genuinely cannot be known yet.

    The one seed hosts whichever of the survivors finished lowest, so a
    divisional pairing drawn from seeds alone would be a guess dressed as a
    fixture.
    """
    partial = games_2025[games_2025["game_type"] == "REG"]
    built = bracket.build(season, partial, playoff_seeds(season, partial))

    div = _round(built, "DIV")["games"]
    # Four games: each conference's one seed at home, and one all-slots game.
    hosts = [tie.home.label for tie in div]
    assert hosts.count("1 seed") == 2
    assert hosts.count("Wild Card winner") == 2
    assert all(tie.away.label == "Wild Card winner" for tie in div)

    assert [s.label for s in (_round(built, "SB")["games"][0].home,
                              _round(built, "SB")["games"][0].away)] == [
        "AFC champion", "NFC champion",
    ]


def test_a_finished_january_is_the_games_that_were_actually_played(season, games_2025):
    """Real results replace the slots, with their scores and their winners."""
    seeds = playoff_seeds(season, games_2025)
    built = bracket.build(season, games_2025, seeds)

    for code in ("WC", "DIV", "CON", "SB"):
        for tie in _round(built, code)["games"]:
            assert tie.known, code
            assert tie.played, code
            assert tie.game_id
            assert tie.home.score is not None and tie.away.score is not None
            # Exactly one side won, and it is the one with more points.
            assert tie.home.won != tie.away.won
            winner = tie.home if tie.home.won else tie.away
            loser = tie.away if tie.home.won else tie.home
            assert winner.score > loser.score


def test_a_fixture_that_is_set_but_not_played_shows_no_score(season, games_2025):
    """The fortnight between the championship games and the Super Bowl.

    Both teams are known and the game has not happened, which is a state the
    bracket is in for two weeks every year. Reading a score off the row anyway
    is how a scheduled game ends up rendered as a result.
    """
    upcoming = games_2025.copy()
    upcoming.loc[upcoming["game_type"] == "SB", ["played", "home_won", "away_won"]] = False

    tie = _round(bracket.build(season, upcoming, playoff_seeds(season, upcoming)), "SB")["games"][0]

    assert tie.known
    assert not tie.played
    assert tie.home.score is None and tie.away.score is None
    assert not tie.home.won and not tie.away.won


def test_the_super_bowl_belongs_to_neither_conference(season, games_2025):
    final = _round(bracket.build(season, games_2025, playoff_seeds(season, games_2025)), "SB")
    tie = final["games"][0]

    assert tie.conference == ""
    assert season.conf_of[tie.home.team] != season.conf_of[tie.away.team]


def test_a_bracket_can_be_built_from_nothing_at_all(season):
    """An empty results frame is a legitimate state on a fresh season."""
    import pandas as pd

    built = bracket.build(season, pd.DataFrame(), None)
    assert sum(len(r["games"]) for r in built) == 13
    assert all(not tie.known for r in built for tie in r["games"])
