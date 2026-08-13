"""Config loading and picks validation.

Every one of these failures would otherwise be silent and cost someone points
for a whole season, so each must raise with a message that names the fix.
"""

from __future__ import annotations

import pytest

from football_pool.season import ConfigError


def test_loads_teams_and_leveling_factors(season):
    assert season.n_teams == 32
    assert season.lf_of("ARI") == 2.60
    assert season.lf_of("SEA") == 1.10
    assert season.div_of["KC"] == "AFC West"
    assert season.conf_of["KC"] == "AFC"
    assert season.conf_of["PHI"] == "NFC"


def test_pot_derives_from_actual_entrant_count(make_season):
    """The pot must not assume 30 people — it follows the picks file."""
    s = make_season(
        [
            {"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]},
            {"name": "B", "teams": ["BUF", "SF", "GB", "MIA"]},
            {"name": "C", "teams": ["CIN", "WAS", "TEN", "NO"]},
        ]
    )
    assert s.pot == 3 * s.entry_fee
    assert s.payouts == pytest.approx(
        (0.5 * s.pot, 0.3 * s.pot, 0.2 * s.pot)
    )


def test_slugs_are_url_safe_and_stable(make_season):
    s = make_season([{"name": "Aunt Carol O'Brien", "teams": ["KC", "SEA", "DAL", "NE"]}])
    assert s.entrants[0].slug == "aunt-carol-o-brien"


def test_picks_matrix_marks_exactly_the_picked_teams(season):
    m = season.picks_matrix()
    assert m.shape == (1, 32)
    assert m.sum() == 4
    for t in ("KC", "SEA", "DAL", "NE"):
        assert m[0, season.idx[t]] == 1.0


@pytest.mark.parametrize(
    "entrants, expect",
    [
        ([{"name": "A", "teams": ["TODO", "TODO", "TODO", "TODO"]}], "placeholder"),
        ([{"name": "A", "teams": ["KC", "SEA", "DAL"]}], "needs exactly 4"),
        ([{"name": "A", "teams": ["KC", "KC", "DAL", "NE"]}], "duplicate team"),
        ([{"name": "A", "teams": ["KAN", "SEA", "DAL", "NE"]}], "unknown team code"),
        (
            [
                {"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]},
                {"name": "a", "teams": ["BUF", "SF", "GB", "MIA"]},
            ],
            "duplicate entrant name",
        ),
    ],
)
def test_bad_picks_fail_loudly(make_season, entrants, expect):
    with pytest.raises(ConfigError, match=expect):
        make_season(entrants)


def test_bare_no_in_yaml_is_caught_not_silently_dropped(tmp_path, season_writer):
    """YAML 1.1 reads a bare NO as false, which would erase the Saints."""
    from football_pool.season import load_season

    season_writer(tmp_path, 2026, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    picks = tmp_path / "seasons" / "2026" / "picks.yaml"
    # Emit the unquoted form a human would hand-write.
    picks.write_text("entrants:\n  - name: A\n    teams: [CAR, TB, ATL, NO]\n")
    with pytest.raises(ConfigError, match="quote it"):
        load_season(2026, root=tmp_path)


def test_rules_and_divisions_must_agree(make_season):
    with pytest.raises(ConfigError, match="disagree"):
        make_season(rules_overrides={"leveling_factors": {"XXX": 1.0}})


def test_conference_helpers(season):
    afc = season.conference_teams("AFC")
    assert len(afc) == 16
    assert "KC" in afc and "PHI" not in afc
    divs = season.conference_divisions("NFC")
    assert len(divs) == 4
    assert {"SEA", "LAR", "SF", "ARI"} in [set(d) for d in divs]


def test_active_season_comes_from_config(tmp_path, season_writer):
    from football_pool.season import active_season

    season_writer(tmp_path, 2031, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    assert active_season(tmp_path) == 2031


def test_load_season_defaults_to_active_season(tmp_path, season_writer):
    from football_pool.season import load_season

    season_writer(tmp_path, 2031, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    assert load_season(root=tmp_path).year == 2031


def test_missing_season_directory_suggests_the_fix(tmp_path, season_writer):
    from football_pool.season import load_season

    season_writer(tmp_path, 2026, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    with pytest.raises(ConfigError, match="cp -r"):
        load_season(2099, root=tmp_path)


def test_missing_and_malformed_config_files(tmp_path):
    from football_pool.season import _read_yaml

    with pytest.raises(ConfigError, match="missing config file"):
        _read_yaml(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n")
    with pytest.raises(ConfigError, match="did not parse to a mapping"):
        _read_yaml(bad)


def test_forecast_is_optional_and_never_required(tmp_path, season_writer):
    """Scoring must work with no forecast file at all."""
    import yaml

    from football_pool.season import load_season

    sdir = season_writer(
        tmp_path, 2026, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}], forecast=False
    )
    assert load_season(2026, root=tmp_path).forecast is None

    (sdir / "forecast.yaml").write_text(yaml.safe_dump({"enabled": False, "simulations": 10}))
    assert load_season(2026, root=tmp_path).forecast is None

    (sdir / "forecast.yaml").write_text(yaml.safe_dump({"enabled": True, "simulations": 10}))
    assert load_season(2026, root=tmp_path).forecast["simulations"] == 10


@pytest.mark.parametrize("section", ["leveling_factors", "divisions"])
def test_dropping_a_team_section_names_it(tmp_path, season_writer, section):
    import yaml

    from football_pool.season import load_season

    sdir = season_writer(tmp_path, 2026, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    rules = yaml.safe_load((sdir / "rules.yaml").read_text())
    del rules[section]
    (sdir / "rules.yaml").write_text(yaml.safe_dump(rules))
    with pytest.raises(ConfigError, match=f"missing section '{section}'"):
        load_season(2026, root=tmp_path)


def test_dropping_a_required_rules_section(tmp_path, season_writer):
    import yaml

    from football_pool.season import load_season

    sdir = season_writer(tmp_path, 2026, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    rules = yaml.safe_load((sdir / "rules.yaml").read_text())
    del rules["scoring"]
    (sdir / "rules.yaml").write_text(yaml.safe_dump(rules))
    with pytest.raises(ConfigError, match="missing section"):
        load_season(2026, root=tmp_path)


def test_malformed_playoff_stage_is_reported(make_season):
    with pytest.raises(ConfigError, match=r"scoring.divisional_win must be"):
        make_season(rules_overrides={"scoring": {"divisional_win": 1.0}})


def _rewrite_rules(sdir, mutate):
    """Load, mutate and rewrite a season's rules.yaml."""
    import yaml

    rules = yaml.safe_load((sdir / "rules.yaml").read_text())
    mutate(rules)
    (sdir / "rules.yaml").write_text(yaml.safe_dump(rules))


def test_wrong_team_count_is_rejected(tmp_path, season_writer):
    """A short but internally consistent league is still rejected."""
    from football_pool.season import load_season

    sdir = season_writer(tmp_path, 2026, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])

    def mutate(rules):
        keep = ["KC", "SEA", "DAL", "NE"]
        rules["leveling_factors"] = {t: 2.0 for t in keep}
        rules["divisions"] = {"AFC West": keep}

    _rewrite_rules(sdir, mutate)
    with pytest.raises(ConfigError, match="expected 32 teams"):
        load_season(2026, root=tmp_path)


def test_non_positive_leveling_factor_is_rejected(make_season):
    with pytest.raises(ConfigError, match="must be positive"):
        make_season(rules_overrides={"leveling_factors": {"KC": 0.0}})


def test_team_in_two_divisions_is_rejected(tmp_path, season_writer):
    """Names the duplicated team rather than reporting a vague set mismatch."""
    from football_pool.season import load_season

    sdir = season_writer(tmp_path, 2026, [{"name": "A", "teams": ["KC", "SEA", "DAL", "NE"]}])
    _rewrite_rules(sdir, lambda r: r["divisions"].__setitem__("AFC East", ["NE", "BUF", "MIA", "KC"]))
    with pytest.raises(ConfigError, match=r"more than one division: \['KC'\]"):
        load_season(2026, root=tmp_path)


@pytest.mark.parametrize(
    "entrants, expect",
    [
        ([], "non-empty"),
        ([{"name": "A"}], "needs both"),
        ([{"name": "  ", "teams": ["KC", "SEA", "DAL", "NE"]}], "name is empty"),
        ([{"name": "A", "teams": "KC"}], "must be a list"),
    ],
)
def test_malformed_entrant_rows(make_season, entrants, expect):
    with pytest.raises(ConfigError, match=expect):
        make_season(entrants)


def test_colliding_slugs_are_rejected(make_season):
    with pytest.raises(ConfigError, match="slug"):
        make_season(
            [
                {"name": "Bob Smith", "teams": ["KC", "SEA", "DAL", "NE"]},
                {"name": "bob!smith", "teams": ["BUF", "SF", "GB", "MIA"]},
            ]
        )


def test_repo_rules_file_is_valid():
    """The committed 2026 rules must always parse — picks may still be TODO."""
    import yaml

    from football_pool.season import REPO_ROOT, _parse_scoring, _parse_teams

    sdir = REPO_ROOT / "seasons" / "2026"
    rules = yaml.safe_load((sdir / "rules.yaml").read_text())
    teams, lf, divisions = _parse_teams(rules, sdir)
    assert len(teams) == 32
    assert len(divisions) == 8
    bonuses, win_mult, tie_mult = _parse_scoring(rules, sdir)
    assert bonuses.division_winner == 3.0
    assert bonuses.wild_card_berth == 1.5
    assert bonuses.wild_card_upset_add_lf is False
    assert (win_mult, tie_mult) == (1.0, 0.5)
