"""Shared fixtures.

Season fixtures are built by writing real YAML into a temp dir and loading it
through the real loader, so the config parser is exercised by every test rather
than bypassed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
import yaml

from football_pool.nflverse import parse_games
from football_pool.season import REPO_ROOT, load_season

FIXTURES = Path(__file__).parent / "fixtures"


REAL_2026 = REPO_ROOT / "seasons" / "2026"

# Keys that live in pools/<slug>.yaml rather than rules.yaml. write_season
# routes overrides by key so a test can say `rules_overrides={"entry_fee": 25}`
# without caring which file the loader keeps it in — that is the loader's
# business, and it has already moved once.
POOL_KEYS = frozenset(
    {"name", "root", "entry_fee", "payout_split", "picks_per_entrant", "venmo"}
)


def write_season(
    root: Path,
    year: int,
    entrants: list[dict],
    *,
    rules_overrides: dict | None = None,
    forecast: bool = True,
    sims: int | None = 50,
    pools: dict[str, dict] | None = None,
) -> Path:
    """Create ``root/seasons/<year>/`` from the repo's real rules plus picks.

    The forecast file is copied too, so projection tests exercise the same
    market inputs the real site uses. Pass ``forecast=False`` to build a season
    with projections switched off.

    The copy's ``simulations:`` line is rewritten to ``sims`` (default 50),
    because the real file says 25,000 and a render that doesn't pass an
    explicit count would otherwise silently run the full Monte Carlo — which
    once cost the suite fourteen seconds without a single test asserting on
    the numbers. Pass ``sims=None`` for a verbatim copy.

    ``entrants`` becomes the root pool, ``family``. Pass ``pools`` — a
    ``{slug: {...}}`` mapping, each value a pool file's contents — to add more.
    """
    sdir = root / "seasons" / str(year)
    (sdir / "pools").mkdir(parents=True, exist_ok=True)

    if forecast:
        text = (REAL_2026 / "forecast.yaml").read_text()
        if sims is not None:
            text = re.sub(r"(?m)^simulations: \d+$", f"simulations: {sims}", text, count=1)
        (sdir / "forecast.yaml").write_text(text)

    rules = yaml.safe_load((REAL_2026 / "rules.yaml").read_text())
    family = yaml.safe_load((REAL_2026 / "pools" / "family.yaml").read_text())
    family["entrants"] = entrants
    rules["season"] = year

    for k, v in (rules_overrides or {}).items():
        target = family if k in POOL_KEYS else rules
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            target[k] = {**target[k], **v}
        else:
            target[k] = v

    (sdir / "rules.yaml").write_text(yaml.safe_dump(rules))
    (sdir / "pools" / "family.yaml").write_text(yaml.safe_dump(family))
    for slug, cfg in (pools or {}).items():
        (sdir / "pools" / f"{slug}.yaml").write_text(yaml.safe_dump(cfg))
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


def build_two_pools(root: Path):
    """One 2025 season, two pools — the shape the real site now has.

    Deliberately different in every way a pool is allowed to differ: name,
    entry fee, payout ladder and field size. A test that only passes because
    the two pools happen to be identical fails against this.

    A plain function rather than only a fixture so test_render.py's
    module-scoped built-site fixtures can construct the same pair without
    going through the function-scoped ``tmp_path``.
    """
    from football_pool.season import load_pools

    write_season(
        root,
        2025,
        [
            {"name": "Aunt Carol", "teams": ["SEA", "NE", "PHI", "LAR"]},
            {"name": "Cousin Mike", "teams": ["KC", "CIN", "DAL", "NO"]},
            {"name": "Brandon", "teams": ["ARI", "NYJ", "TEN", "CLE"]},
        ],
        pools={
            "friends": {
                "name": "Friends Pool",
                "entry_fee": 50.0,
                "payout_split": [0.6, 0.4],
                "entrants": [
                    {"name": "Dana", "teams": ["BUF", "SF", "GB", "MIA"]},
                    {"name": "Priya", "teams": ["LAR", "SEA", "KC", "NE"]},
                ],
            }
        },
    )
    return load_pools(2025, root=root)


@pytest.fixture
def two_pools(tmp_path):
    return build_two_pools(tmp_path)


@pytest.fixture(scope="session")
def games_2025():
    """Every 2025 game, already final — a complete season to replay.

    Session-scoped: the suite reads this frame hundreds of times and nothing
    needs a private copy. Consumers must ``.copy()`` before mutating.
    """
    return parse_games(FIXTURES / "games_2025.csv", 2025)
