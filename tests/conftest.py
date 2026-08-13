"""Shared fixtures.

Season fixtures are built by writing real YAML into a temp dir and loading it
through the real loader, so the config parser is exercised by every test rather
than bypassed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from football_pool.nflverse import parse_games
from football_pool.season import REPO_ROOT, load_season

FIXTURES = Path(__file__).parent / "fixtures"


def write_season(
    root: Path,
    year: int,
    entrants: list[dict],
    *,
    rules_overrides: dict | None = None,
    forecast: bool = True,
) -> Path:
    """Create ``root/seasons/<year>/`` from the repo's real rules plus picks.

    The forecast file is copied too, so projection tests exercise the same
    market inputs the real site uses. Pass ``forecast=False`` to build a season
    with projections switched off.
    """
    sdir = root / "seasons" / str(year)
    sdir.mkdir(parents=True, exist_ok=True)

    if forecast:
        shutil.copy(REPO_ROOT / "seasons" / "2026" / "forecast.yaml", sdir / "forecast.yaml")

    rules = yaml.safe_load((REPO_ROOT / "seasons" / "2026" / "rules.yaml").read_text())
    rules["season"] = year
    for k, v in (rules_overrides or {}).items():
        if isinstance(v, dict) and isinstance(rules.get(k), dict):
            rules[k] = {**rules[k], **v}
        else:
            rules[k] = v
    (sdir / "rules.yaml").write_text(yaml.safe_dump(rules))
    (sdir / "picks.yaml").write_text(yaml.safe_dump({"entrants": entrants}))
    (root / "config.yaml").write_text(yaml.safe_dump({"active_season": year}))
    return sdir


@pytest.fixture
def season_writer():
    """The raw config writer, for tests that need to hand-craft bad YAML."""
    return write_season


@pytest.fixture
def make_season(tmp_path):
    """Factory: build and load a Season with the given entrants."""

    def _make(entrants: list[dict] | None = None, year: int = 2026, **kw):
        if entrants is None:  # an explicit [] must stay empty, not get defaulted
            entrants = [{"name": "Solo", "teams": ["KC", "SEA", "DAL", "NE"]}]
        write_season(tmp_path, year, entrants, **kw)
        return load_season(year, root=tmp_path)

    return _make


@pytest.fixture
def season(make_season):
    return make_season()


@pytest.fixture
def games_2025():
    """Every 2025 game, already final — a complete season to replay."""
    return parse_games(FIXTURES / "games_2025.csv", 2025)
