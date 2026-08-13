"""Command line behaviour, including that config errors are legible."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from football_pool import cli
from football_pool.nflverse import GameData, parse_games

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def wired(monkeypatch, season):
    """Point the CLI at the fixture season and fixture games, no network."""
    games = parse_games(FIXTURES / "games_2025.csv", 2025)
    gd = GameData(games, 2025, datetime(2026, 2, 10, tzinfo=timezone.utc),
                  datetime(2026, 2, 9, tzinfo=timezone.utc), "cache")
    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr("football_pool.nflverse.fetch_games", lambda *a, **k: gd)
    return season, gd


def test_standings_prints_a_leaderboard(wired, capsys):
    season, _ = wired
    assert cli.main(["standings"]) == 0
    out = capsys.readouterr().out
    assert "Solo" in out
    assert f"pot ${season.pot:,.0f}" in out
    assert "through week 18" in out
    # The entrant's four teams appear with their point contributions.
    for team in ("KC", "SEA", "DAL", "NE"):
        assert team in out


def test_standings_says_preseason_when_nothing_is_played(monkeypatch, season, capsys):
    games = parse_games(FIXTURES / "games_2025.csv", 2025).copy()
    games["played"] = False
    games["home_won"] = False
    games["away_won"] = False
    games["is_tie"] = False
    gd = GameData(games, 2025, datetime.now(timezone.utc), None, "cache")
    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr("football_pool.nflverse.fetch_games", lambda *a, **k: gd)

    assert cli.main(["standings"]) == 0
    assert "preseason, no games played" in capsys.readouterr().out


def test_fetch_reports_counts_and_provenance(monkeypatch, capsys):
    games = parse_games(FIXTURES / "games_2025.csv", 2025)
    gd = GameData(games, 2025, datetime.now(timezone.utc),
                  datetime(2026, 2, 9, tzinfo=timezone.utc), "network")
    monkeypatch.setattr("football_pool.nflverse.fetch_games", lambda *a, **k: gd)
    monkeypatch.setattr(cli, "active_season", lambda: 2025)

    assert cli.main(["fetch"]) == 0
    out = capsys.readouterr().out
    assert "285 games, 285 played" in out
    assert "[network]" in out
    assert "upstream last modified" in out


def test_fetch_omits_the_upstream_line_when_unknown(monkeypatch, capsys):
    """Serving from cache means there is no upstream timestamp to report."""
    games = parse_games(FIXTURES / "games_2025.csv", 2025)
    gd = GameData(games, 2025, datetime.now(timezone.utc), None, "cache")
    monkeypatch.setattr("football_pool.nflverse.fetch_games", lambda *a, **k: gd)
    monkeypatch.setattr(cli, "active_season", lambda: 2025)

    assert cli.main(["fetch"]) == 0
    out = capsys.readouterr().out
    assert "[cache]" in out
    assert "upstream last modified" not in out


def test_config_errors_are_printed_not_raised(monkeypatch, capsys):
    """The real picks.yaml still has TODO placeholders — that must read clearly."""
    from football_pool.season import ConfigError

    def boom(year):
        raise ConfigError("Brandon still has placeholder picks ['TODO']")

    monkeypatch.setattr(cli, "load_season", boom)
    assert cli.main(["standings"]) == 1
    err = capsys.readouterr().err
    assert "config error" in err
    assert "placeholder picks" in err


def test_build_writes_a_site(wired, capsys, tmp_path):
    out = tmp_path / "site"
    assert cli.main(["build", "--out", str(out)]) == 0

    assert (out / "index.html").exists()
    assert (out / "assets" / "site.css").exists()
    report = capsys.readouterr().out
    assert "built" in report and "pages" in report
    assert "through week 18" in report


def test_build_applies_the_deployment_base(wired, tmp_path):
    out = tmp_path / "site"
    assert cli.main(["build", "--out", str(out), "--base", "/football-pool"]) == 0
    # The asset URL carries the deployment prefix and a cache-busting stamp, so
    # this matches the prefix rather than the whole attribute.
    assert '"/football-pool/assets/site.css?v=' in (out / "index.html").read_text()


def test_build_reports_preseason(monkeypatch, season, capsys, tmp_path):
    games = parse_games(FIXTURES / "games_2025.csv", 2025).copy()
    games[["played", "home_won", "away_won", "is_tie"]] = False
    gd = GameData(games, 2025, datetime.now(timezone.utc), None, "cache")
    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr("football_pool.nflverse.fetch_games", lambda *a, **k: gd)

    assert cli.main(["build", "--out", str(tmp_path / "s")]) == 0
    assert "preseason, no games played yet" in capsys.readouterr().out


def test_check_lf_reports_the_comparison(monkeypatch, season, capsys):
    """Compares the configured factors against the prior season's records."""
    prior = parse_games(FIXTURES / "games_2025.csv", 2025)
    gd = GameData(prior, 2025, datetime.now(timezone.utc), None, "cache")
    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr("football_pool.nflverse.fetch_games", lambda *a, **k: gd)

    assert cli.main(["check-lf", "--prior", "2025"]) == 0
    out = capsys.readouterr().out

    assert "leveling factors vs 2025 records" in out
    assert "-- AFC --" in out and "-- NFC --" in out
    assert "31/32 match" in out
    # The one deliberate tiebreak is surfaced, not hidden.
    assert "DEN" in out and "NE" in out
    assert "worth a look" in out


def test_check_lf_is_quiet_on_a_clean_table(monkeypatch, make_season, capsys, games_2025):
    """A table generated straight from the structure raises nothing."""
    from football_pool.leveling import propose_leveling_factors

    base = make_season([{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    clean = make_season(
        [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}],
        rules_overrides={"leveling_factors": propose_leveling_factors(base, games_2025)},
    )
    gd = GameData(games_2025, 2025, datetime.now(timezone.utc), None, "cache")
    monkeypatch.setattr(cli, "load_season", lambda year: clean)
    monkeypatch.setattr("football_pool.nflverse.fetch_games", lambda *a, **k: gd)

    assert cli.main(["check-lf"]) == 0
    out = capsys.readouterr().out
    assert "32/32 match" in out
    assert "Nothing inconsistent found" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["--season", "2025", "fetch"],  # before the subcommand
        ["fetch", "--season", "2025"],  # after it — the way people actually type it
    ],
)
def test_season_flag_works_on_either_side_of_the_subcommand(monkeypatch, capsys, argv):
    """Both forms must select the same season.

    argparse's `parents=` has a trap here: with an ordinary default, the
    subparser overwrites whatever the main parser already parsed, so one of
    these would silently operate on the wrong year.
    """
    seen = {}

    def spy(season, **kwargs):
        seen["season"] = season
        games = parse_games(FIXTURES / "games_2025.csv", 2025)
        return GameData(games, season, datetime.now(timezone.utc), None, "cache")

    monkeypatch.setattr("football_pool.nflverse.fetch_games", spy)
    monkeypatch.setattr(cli, "active_season", lambda: 2026)

    assert cli.main(argv) == 0
    assert seen["season"] == 2025
    assert "season 2025" in capsys.readouterr().out


def test_offline_flag_works_after_the_subcommand(monkeypatch, season):
    seen = {}

    def spy(year, **kwargs):
        seen.update(kwargs)
        games = parse_games(FIXTURES / "games_2025.csv", 2025)
        return GameData(games, 2025, datetime.now(timezone.utc), None, "cache")

    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr("football_pool.nflverse.fetch_games", spy)

    assert cli.main(["standings", "--offline"]) == 0
    assert seen["offline"] is True


def test_no_subcommand_prints_help(capsys):
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_path_helpers_are_season_scoped(tmp_path):
    assert cli.data_dir(2026, tmp_path) == tmp_path / "data" / "2026"
    assert cli.games_cache(2027, tmp_path).name == "games.csv"
    assert "2027" in str(cli.games_cache(2027, tmp_path))


# -- refusing to publish stale data ------------------------------------------
def _stale_data(games, source):
    """A fallback holding preseason data, consulted deep into the season."""
    frozen = games.copy()
    frozen[["played", "home_won", "away_won", "is_tie"]] = False
    return GameData(frozen, 2025, datetime(2025, 12, 1, tzinfo=timezone.utc), None, source)


def test_build_refuses_to_publish_a_stale_fallback(monkeypatch, season, tmp_path, capsys):
    """The failure this guard exists for.

    The daily job cannot refresh the committed copy while main is protected, so
    it sits at preseason. If the feed is unreachable in week 12, publishing it
    would replace a correct leaderboard with an all-zeros one — and a silently
    wrong board looks exactly like a right one to whoever opens it.
    """
    games = parse_games(FIXTURES / "games_2025.csv", 2025)
    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr(
        "football_pool.nflverse.fetch_games",
        lambda *a, **k: _stale_data(games, "fallback"),
    )

    out = tmp_path / "site"
    assert cli.main(["build", "--out", str(out)]) == 1

    err = capsys.readouterr().err
    assert "refusing to publish" in err
    assert "regular-season games" in err
    assert "DATA_PUSH_TOKEN" in err  # tells the operator how to fix it
    assert not (out / "index.html").exists(), "nothing may be written"


def test_an_explicit_offline_build_is_never_blocked(monkeypatch, season, tmp_path):
    """CI builds --offline on purpose, and must stay green all season.

    Identical bytes to the case above; only the provenance differs. That is the
    whole reason "cache" and "fallback" are separate values.
    """
    games = parse_games(FIXTURES / "games_2025.csv", 2025)
    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr(
        "football_pool.nflverse.fetch_games",
        lambda *a, **k: _stale_data(games, "cache"),
    )

    out = tmp_path / "site"
    assert cli.main(["build", "--out", str(out), "--offline"]) == 0
    assert (out / "index.html").exists()


def test_a_fallback_that_is_merely_recent_still_publishes(monkeypatch, season, tmp_path):
    """An outage on an ordinary day degrades to yesterday's numbers, as designed.

    The guard is for data that is behind by a slate, not for any fallback at
    all — otherwise a single flaky morning would stop the site updating.
    """
    games = parse_games(FIXTURES / "games_2025.csv", 2025)
    fresh = GameData(
        games, 2025, datetime(2026, 6, 1, tzinfo=timezone.utc), None, "fallback"
    )
    assert fresh.staleness_reason() is None

    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr("football_pool.nflverse.fetch_games", lambda *a, **k: fresh)

    out = tmp_path / "site"
    assert cli.main(["build", "--out", str(out)]) == 0
    assert (out / "index.html").exists()


def test_a_preseason_fallback_publishes_because_nothing_is_late(
    monkeypatch, season, tmp_path
):
    """In August a schedule with no results is correct, not stale.

    This is why the measure counts overdue games rather than the age of the
    file: the committed copy can be months old and still perfectly current.
    """
    games = parse_games(FIXTURES / "games_2025.csv", 2025)
    preseason = games.copy()
    preseason[["played", "home_won", "away_won", "is_tie"]] = False
    before_kickoff = GameData(
        preseason, 2025, datetime(2025, 8, 1, tzinfo=timezone.utc), None, "fallback"
    )
    assert before_kickoff.staleness_reason() is None

    monkeypatch.setattr(cli, "load_season", lambda year: season)
    monkeypatch.setattr(
        "football_pool.nflverse.fetch_games", lambda *a, **k: before_kickoff
    )

    assert cli.main(["build", "--out", str(tmp_path / "s")]) == 0
