"""Season configuration — everything that changes from one year to the next.

The whole point of this module is that no pool rule, leveling factor, entrant,
or dollar figure is ever a constant in code. A :class:`Season` is loaded from
``seasons/<year>/`` and threaded through every other module, so building a
different year is a different argument, not a different program.

One year can carry more than one pool. The split is by owner: ``rules.yaml``
holds what the commissioner sets and every pool shares — the leveling factors,
the scoring table, the divisions — while ``pools/<slug>.yaml`` holds what one
group of people decides for itself: its name, its entry fee, its payout ladder,
and its roster. There is therefore exactly one leveling-factor table per year
and no way for two pools to drift apart on what a win is worth.

A loaded :class:`Season` is still one object per pool, carrying that pool's
money and entrants alongside the shared rules, because that is the shape every
other module already reads. Which pool it is lives in :attr:`Season.pool`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

# Upstream data uses a few different codes than the pool does. Normalization
# happens at exactly one boundary (see nflverse.parse_games); everything
# downstream speaks pool codes.
TEAM_ALIASES: dict[str, str] = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX"}


def _find_repo_root() -> Path:
    """Locate the directory holding config.yaml, seasons/, and templates/.

    ``Path(__file__).parents[2]`` is only the repo root when running from a
    source checkout. Installed as a wheel it resolves to site-packages'
    grandparent (e.g. ``/usr/local/lib/python3.12``), where none of the data
    files exist — which made the packaged ``pool`` console script dead on
    arrival. Resolution order:

    1. ``POOL_ROOT`` environment variable, set explicitly.
    2. Walking up from this file — finds the checkout root when running from
       source, exactly as before.
    3. The current working directory — so an installed ``pool`` works when run
       from inside a checkout.
    """
    env = os.environ.get("POOL_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config.yaml").is_file() and (parent / "seasons").is_dir():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()


class ConfigError(Exception):
    """Raised when the season config is wrong in a way a human must fix.

    These are deliberately loud. A typo in picks.yaml would otherwise silently
    score someone zero for a team all season, and nobody would notice until
    Thanksgiving.
    """


@dataclass(frozen=True)
class Bonuses:
    """Point values for everything that is not a regular-season win."""

    division_winner: float
    wild_card_berth: float
    wild_card_upset_flat: float
    wild_card_upset_add_lf: bool
    divisional_flat: float
    divisional_add_lf: bool
    conference_flat: float
    conference_add_lf: bool
    super_bowl_flat: float
    super_bowl_add_lf: bool


@dataclass(frozen=True)
class PoolInfo:
    """Which pool this is: its name, its URL segment, its storage scope.

    Identity only. The money and the roster live on :class:`Season`, where
    every caller already reads them.
    """

    slug: str
    name: str
    root: bool = False

    @property
    def path(self) -> str:
        """URL segment and output subdirectory — ``""`` for the pool at the root.

        The root pool has no segment because its URLs predate there being more
        than one pool, and they are in a year of group-chat links. The empty
        string is also what keeps its localStorage keys unsuffixed, so a
        returning visitor's saved identity survives the second pool arriving.
        """
        return "" if self.root else self.slug


# Directory names the renderer already claims. A pool slugged `teams` would
# write its board over the teams page, and one slugged `entrant` would be
# deleted outright by the prune in render_site. Checked in _discover_pools.
RESERVED_SLUGS = frozenset(
    {
        "404",
        "assets",
        "data",
        "entrant",
        "forecast",
        "index",
        "rules",
        "schedule",
        "season",
        "teams",
        "trends",
        "weeks",
    }
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class Entrant:
    """One person's entry: a name and the teams they picked."""

    name: str
    teams: tuple[str, ...]

    @property
    def slug(self) -> str:
        """URL-safe id, stable across builds (used for /entrant/<slug>/)."""
        s = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        return s or "entrant"


@dataclass(frozen=True)
class Season:
    """A fully-resolved season: rules, teams, entrants, and derived arrays."""

    year: int
    teams: tuple[str, ...]
    lf: np.ndarray  # (32,) leveling factor, indexed by team position
    divisions: Mapping[str, tuple[str, ...]]
    bonuses: Bonuses
    win_multiplier: float
    tie_multiplier: float
    entry_fee: float
    payout_split: tuple[float, ...]
    picks_per_entrant: int
    entrants: tuple[Entrant, ...]
    forecast: Mapping[str, Any] | None = None

    # Which pool this is, and every pool sharing the season (root first, for
    # the switcher). Defaulted so a Season can still be built without a pools
    # directory in sight.
    pool: PoolInfo = PoolInfo(slug="pool", name="The Pool", root=True)
    pools: tuple[PoolInfo, ...] = ()
    # Where this season was loaded from, so a caller holding one pool can find
    # its siblings without being told the root a second time. Spelled out
    # rather than `root`, which on PoolInfo next door means something else
    # entirely (is this the pool at the site root).
    config_root: Path | None = None

    # Derived lookups, built in __post_init__.
    idx: Mapping[str, int] = field(default_factory=dict)
    div_of: Mapping[str, str] = field(default_factory=dict)
    conf_of: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "idx", {t: i for i, t in enumerate(self.teams)})
        div_of = {t: d for d, ts in self.divisions.items() for t in ts}
        object.__setattr__(self, "div_of", div_of)
        object.__setattr__(
            self, "conf_of", {t: d.split()[0] for t, d in div_of.items()}
        )

    # -- convenience ------------------------------------------------------
    @property
    def n_teams(self) -> int:
        return len(self.teams)

    @property
    def pot(self) -> float:
        """Total money in the pool.

        Derived from the actual entrant count rather than an assumed 30, so
        every dollar figure on the site stays correct as picks trickle in.
        """
        return len(self.entrants) * self.entry_fee

    @property
    def payouts(self) -> tuple[float, ...]:
        """Dollar payout for 1st, 2nd, 3rd."""
        return tuple(self.pot * s for s in self.payout_split)

    def lf_of(self, team: str) -> float:
        return float(self.lf[self.idx[team]])

    def picks_matrix(self) -> np.ndarray:
        """(n_entrants, n_teams) 0/1 matrix — entrant totals are a matmul away."""
        m = np.zeros((len(self.entrants), self.n_teams))
        for i, e in enumerate(self.entrants):
            m[i, [self.idx[t] for t in e.teams]] = 1.0
        return m

    def conference_teams(self, conf: str) -> list[str]:
        return [t for t in self.teams if self.conf_of[t] == conf]

    def conference_divisions(self, conf: str) -> list[tuple[str, ...]]:
        return [ts for d, ts in self.divisions.items() if d.startswith(conf)]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def team_code(value: Any, where: str) -> str:
    """Coerce a YAML scalar to a team code, catching the YAML 1.1 boolean trap.

    YAML 1.1 reads a bare ``NO`` as the boolean ``false``, which would silently
    erase New Orleans from the pool. Every team code in the config files is
    quoted for that reason; this catches it if one ever isn't.
    """
    if isinstance(value, bool):
        raise ConfigError(
            f"{where}: found the boolean {str(value).lower()!r} where a team code "
            f"was expected. YAML reads a bare NO as false — quote it as \"NO\"."
        )
    return str(value).strip().upper()


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"missing config file: {path}")
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} did not parse to a mapping")
    return data


def active_season(root: Path | None = None) -> int:
    """The season the site builds by default (from config.yaml)."""
    root = root or REPO_ROOT
    return int(_read_yaml(root / "config.yaml")["active_season"])


def _season_dir(year: int, root: Path) -> Path:
    sdir = root / "seasons" / str(year)
    if not sdir.is_dir():
        raise ConfigError(
            f"no config for season {year} (expected {sdir}). "
            f"To start a new season: cp -r seasons/<prev> {sdir}"
        )
    return sdir


def _discover_pools(sdir: Path) -> tuple[PoolInfo, ...]:
    """Every pool in ``seasons/<year>/pools/``, the one at the site root first.

    Discovery is a glob rather than a manifest on purpose. A manifest can
    disagree with what is on disk in two directions — a pool listed but
    missing, a pool present but unpublished — and both failures are quiet.
    A directory listing cannot disagree with itself.
    """
    pdir = sdir / "pools"
    paths = sorted(pdir.glob("*.yaml")) if pdir.is_dir() else []
    if not paths:
        raise ConfigError(
            f"no pools found in {pdir}. Every season needs at least one: a file "
            f"named <slug>.yaml with `name:`, `root: true`, the money, and an "
            f"`entrants:` list."
        )

    pools: list[PoolInfo] = []
    for path in paths:
        slug = path.stem
        if not _SLUG_RE.match(slug):
            raise ConfigError(
                f"{path}: {slug!r} is not a usable slug. The filename becomes the "
                f"pool's URL, so it must be lowercase letters, digits and hyphens, "
                f"starting with a letter or digit."
            )
        if slug in RESERVED_SLUGS:
            raise ConfigError(
                f"{path}: {slug!r} is a page the site already writes, so this pool "
                f"would overwrite it (or be deleted by it). Reserved: "
                f"{', '.join(sorted(RESERVED_SLUGS))}."
            )
        cfg = _read_yaml(path)
        name = str(cfg.get("name", "")).strip()
        if not name:
            raise ConfigError(f"{path}: needs a `name:` — it is the site's wordmark")
        pools.append(PoolInfo(slug=slug, name=name, root=bool(cfg.get("root", False))))

    roots = [p.slug for p in pools if p.root]
    if len(roots) != 1:
        found = ", ".join(roots) if roots else "none"
        raise ConfigError(
            f"{pdir}: exactly one pool must set `root: true` (found {found}). "
            f"That pool is served at the site root; every other one at /<slug>/."
        )

    # Root first — this is the order the pool switcher lists them in.
    return tuple(sorted(pools, key=lambda p: (not p.root, p.slug)))


def _select_pool(pools: tuple[PoolInfo, ...], slug: str | None, sdir: Path) -> PoolInfo:
    """The named pool, or the one at the site root when nothing is named."""
    if slug is None:
        return next(p for p in pools if p.root)
    for p in pools:
        if p.slug == slug:
            return p
    raise ConfigError(
        f"{sdir / 'pools'}: no pool named {slug!r}. "
        f"This season has: {', '.join(p.slug for p in pools)}."
    )


def load_season(
    year: int | None = None,
    root: Path | None = None,
    pool: str | None = None,
) -> Season:
    """Load one pool of ``seasons/<year>/`` into a :class:`Season`.

    Args:
        pool: Which pool's money and roster to load. ``None`` means the pool
            served at the site root, which is what every caller that predates
            there being two of them wants.

    Raises:
        ConfigError: on any malformed rules or picks. Loud on purpose.
    """
    root = root or REPO_ROOT
    year = year if year is not None else active_season(root)
    sdir = _season_dir(year, root)

    rules = _read_yaml(sdir / "rules.yaml")
    teams, lf, divisions = _parse_teams(rules, sdir)
    bonuses, win_mult, tie_mult = _parse_scoring(rules, sdir)

    pools = _discover_pools(sdir)
    chosen = _select_pool(pools, pool, sdir)
    ppath = sdir / "pools" / f"{chosen.slug}.yaml"
    pcfg = _read_yaml(ppath)

    _validate_money(pcfg, ppath)
    n_picks = int(pcfg.get("picks_per_entrant", 4))
    entrants = _parse_picks(pcfg, set(teams), n_picks, ppath)

    # forecast.yaml is optional and never affects scoring.
    forecast = None
    fpath = sdir / "forecast.yaml"
    if fpath.exists():
        f = _read_yaml(fpath)
        if f.get("enabled", True):
            forecast = f

    return Season(
        year=year,
        teams=teams,
        lf=lf,
        divisions=divisions,
        bonuses=bonuses,
        win_multiplier=win_mult,
        tie_multiplier=tie_mult,
        entry_fee=float(pcfg["entry_fee"]),
        payout_split=tuple(float(x) for x in pcfg["payout_split"]),
        picks_per_entrant=n_picks,
        entrants=entrants,
        forecast=forecast,
        pool=chosen,
        pools=pools,
        config_root=root,
    )


def load_pools(year: int | None = None, root: Path | None = None) -> tuple[Season, ...]:
    """Every pool sharing one season, the site-root pool first.

    Each is a full :class:`Season` carrying the same shared rules. Re-reading
    ``rules.yaml`` per pool costs a few milliseconds and keeps the loader a
    single code path, which is worth considerably more than the saving.
    """
    root = root or REPO_ROOT
    year = year if year is not None else active_season(root)
    pools = _discover_pools(_season_dir(year, root))
    return tuple(load_season(year, root, p.slug) for p in pools)


def _parse_teams(
    rules: dict, sdir: Path
) -> tuple[tuple[str, ...], np.ndarray, dict[str, tuple[str, ...]]]:
    """Teams, leveling factors, and divisions — cross-checked against each other."""
    rules_path = sdir / "rules.yaml"
    try:
        lf_map = {
            team_code(k, f"{rules_path} leveling_factors"): v
            for k, v in rules["leveling_factors"].items()
        }
        divisions = {
            d: tuple(team_code(t, f"{rules_path} divisions.{d}") for t in ts)
            for d, ts in rules["divisions"].items()
        }
    except KeyError as e:
        raise ConfigError(f"{rules_path} is missing section {e}") from e

    teams = tuple(sorted(lf_map))
    all_division_slots = [t for ts in divisions.values() for t in ts]
    in_divisions = set(all_division_slots)

    # Checked before the set comparison: a team listed twice always shows up as
    # a set mismatch too, and "KC is in two divisions" is the message that
    # actually names the mistake.
    dupes = sorted({t for t in all_division_slots if all_division_slots.count(t) > 1})
    if dupes:
        raise ConfigError(f"team(s) listed in more than one division: {dupes}")

    if set(teams) != in_divisions:
        only_lf = sorted(set(teams) - in_divisions)
        only_div = sorted(in_divisions - set(teams))
        raise ConfigError(
            f"{sdir / 'rules.yaml'}: leveling_factors and divisions disagree. "
            f"Only in leveling_factors: {only_lf or 'none'}. "
            f"Only in divisions: {only_div or 'none'}."
        )
    if len(teams) != 32:
        raise ConfigError(f"expected 32 teams in {rules_path}, got {len(teams)}")

    lf = np.array([float(lf_map[t]) for t in teams])
    if np.any(lf <= 0):
        bad = [t for t, v in zip(teams, lf) if v <= 0]
        raise ConfigError(f"leveling factors must be positive; bad: {bad}")
    return teams, lf, divisions


def _parse_scoring(rules: dict, sdir: Path) -> tuple[Bonuses, float, float]:
    try:
        sc = rules["scoring"]
    except KeyError as e:
        raise ConfigError(f"{sdir / 'rules.yaml'} is missing section {e}") from e

    def stage(key: str) -> tuple[float, bool]:
        try:
            d = sc[key]
            return float(d["flat"]), bool(d["add_lf"])
        except (KeyError, TypeError) as e:
            raise ConfigError(
                f"{sdir / 'rules.yaml'}: scoring.{key} must be "
                f"{{flat: <number>, add_lf: <bool>}}"
            ) from e

    wc_flat, wc_lf = stage("wild_card_upset")
    dv_flat, dv_lf = stage("divisional_win")
    cf_flat, cf_lf = stage("conference_win")
    sb_flat, sb_lf = stage("super_bowl_win")

    def flat(key: str) -> float:
        # The staged bonuses already fail with a legible ConfigError; a missing
        # flat bonus used to leak a raw KeyError traceback instead. Same
        # loudness for both.
        try:
            return float(sc[key])
        except (KeyError, TypeError, ValueError) as e:
            raise ConfigError(
                f"{sdir / 'rules.yaml'}: scoring.{key} must be a number"
            ) from e

    bonuses = Bonuses(
        division_winner=flat("division_winner"),
        wild_card_berth=flat("wild_card_berth"),
        wild_card_upset_flat=wc_flat,
        wild_card_upset_add_lf=wc_lf,
        divisional_flat=dv_flat,
        divisional_add_lf=dv_lf,
        conference_flat=cf_flat,
        conference_add_lf=cf_lf,
        super_bowl_flat=sb_flat,
        super_bowl_add_lf=sb_lf,
    )
    return bonuses, float(sc.get("win_multiplier", 1.0)), float(sc.get("tie_multiplier", 0.5))


def _validate_money(pcfg: dict, path: Path) -> None:
    """The dollars get the same hard validation the picks do.

    A payout_split summing past 1.0 pays out more than the pot; a negative
    entry fee produces negative payouts. Both previously loaded silently and
    would have been published as-is.
    """
    try:
        fee = float(pcfg["entry_fee"])
        split = [float(x) for x in pcfg["payout_split"]]
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(
            f"{path}: entry_fee must be a number and payout_split a list of numbers"
        ) from e
    if fee < 0:
        raise ConfigError(f"{path}: entry_fee is negative ({fee})")
    if not split:
        raise ConfigError(f"{path}: payout_split is empty — nobody gets paid")
    if any(s < 0 for s in split):
        raise ConfigError(f"{path}: payout_split has a negative share: {split}")
    if sum(split) > 1.0 + 1e-9:
        raise ConfigError(
            f"{path}: payout_split sums to {sum(split):.2f} — that pays out "
            f"more than 100% of the pot"
        )


def _parse_picks(
    pcfg: dict, valid: set[str], n_required: int, path: Path
) -> tuple[Entrant, ...]:
    """Validate and load one pool's entrants. Every failure mode here is loud."""
    raw = pcfg.get("entrants")
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{path}: needs a non-empty `entrants:` list")

    entrants: list[Entrant] = []
    seen_names: set[str] = set()
    seen_slugs: dict[str, str] = {}

    for i, row in enumerate(raw):
        where = f"{path} entry #{i + 1}"
        if not isinstance(row, dict) or "name" not in row or "teams" not in row:
            raise ConfigError(f"{where}: needs both `name:` and `teams:`")

        name = str(row["name"]).strip()
        if not name:
            raise ConfigError(f"{where}: name is empty")
        if name.lower() in seen_names:
            raise ConfigError(f"{path}: duplicate entrant name {name!r}")
        seen_names.add(name.lower())

        teams_raw = row["teams"]
        if not isinstance(teams_raw, Sequence) or isinstance(teams_raw, str):
            raise ConfigError(f"{where} ({name}): `teams:` must be a list")
        teams = [team_code(t, f"{where} ({name})") for t in teams_raw]

        placeholders = [t for t in teams if t in {"TODO", "TBD", "???", ""}]
        if placeholders:
            raise ConfigError(
                f"{path}: {name} still has placeholder picks {placeholders}. "
                f'Replace them with {n_required} real team codes, quoted '
                f'(e.g. teams: ["CIN", "WAS", "TEN", "NO"] — a bare NO is '
                f"YAML for false)."
            )
        if len(teams) != n_required:
            raise ConfigError(
                f"{where} ({name}): has {len(teams)} teams, needs exactly {n_required}"
            )
        if len(set(teams)) != len(teams):
            dupe = sorted({t for t in teams if teams.count(t) > 1})
            raise ConfigError(f"{where} ({name}): duplicate team(s) {dupe} in one entry")

        unknown = [t for t in teams if t not in valid]
        if unknown:
            raise ConfigError(
                f"{where} ({name}): unknown team code(s) {unknown}. "
                f"Valid codes are the 32 in rules.yaml — note LAR (not LA), "
                f"KC (not KAN), WAS (not WSH), JAX (not JAC)."
            )

        e = Entrant(name=name, teams=tuple(teams))
        if e.slug in seen_slugs:
            raise ConfigError(
                f"{path}: {name!r} and {seen_slugs[e.slug]!r} both produce the URL "
                f"slug {e.slug!r}; make the names more distinct."
            )
        seen_slugs[e.slug] = name
        entrants.append(e)

    return tuple(entrants)
