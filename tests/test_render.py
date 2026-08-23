"""Site generation.

Structural assertions, not golden HTML files. Eighty-odd golden pages would
break on every CSS class rename, and a suite that gets regenerated without
being read is worse than no suite at all.

The base-path tests matter most: a root-absolute asset URL works perfectly on a
local preview server and 404s only once deployed to a project page.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest

from football_pool.history import weekly_frame
from football_pool.nflverse import GameData, parse_games
from football_pool.render import (
    ASSET_DIR,
    MODEL_URL,
    REPO_URL,
    _entrant_rows,
    _bracket,
    _forecast,
    _schedule,
    _team_page,
    _team_rows,
    build_context,
    make_environment,
    render_pools,
    render_site,
)

FIXTURES = Path(__file__).parent / "fixtures"

# A fixed instant, so nothing in here depends on when the suite is run.
NOW = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)

# Enough simulation to produce a projection block, not enough to be slow. The
# multi-pool tests render two whole sites twice over; at forecast.yaml's real
# 25,000 they would dominate the suite, and none of them assert on the numbers.
SIMS = 50


@pytest.fixture
def game_data(games_2025):
    return GameData(
        games_2025,
        2025,
        datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 9, 14, 30, tzinfo=timezone.utc),
        "network",
    )


@pytest.fixture
def preseason_data(games_2025):
    """August: a regular-season slate, nothing played.

    The postseason rows are dropped rather than blanked, because the league
    does not publish a wild-card fixture before it knows who is in it.
    """
    g = games_2025[games_2025["game_type"] == "REG"].copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    return GameData(g, 2025, datetime.now(timezone.utc), None, "cache")


@pytest.fixture
def mid_season(games_2025):
    """Week 11 of 18 — the state the site spends most of its life in."""
    g = games_2025.copy()
    g.loc[g["week"] > 11, "played"] = False
    g.loc[g["game_type"] != "REG", "played"] = False
    return GameData(g, 2025, datetime.now(timezone.utc), None, "cache")


# NB: this `pool` is a Season, and predates there being a PoolInfo of that
# name. It is the three-way field most tests in here render.
@pytest.fixture
def pool(make_season):
    return make_season(
        [
            {"name": "Aunt Carol", "teams": ["SEA", "NE", "PHI", "LAR"]},
            {"name": "Cousin Mike", "teams": ["KC", "CIN", "DAL", "NO"]},
            {"name": "Brandon", "teams": ["ARI", "NYJ", "TEN", "CLE"]},
        ],
        year=2025,
    )


# -- the url filter, the deployment footgun ---------------------------------
# Non-asset paths only: assets additionally carry a cache-busting fingerprint,
# which is asserted separately below so that an edit to site.css cannot turn
# this test into a tripwire on an unrelated commit.
@pytest.mark.parametrize(
    "base, path, expected",
    [
        ("", "/rules/", "/rules/"),
        ("/football-pool", "/rules/", "/football-pool/rules/"),
        ("/football-pool/", "/rules/", "/football-pool/rules/"),
        ("/football-pool", "/", "/football-pool/"),
        ("/football-pool", "/data/standings.json", "/football-pool/data/standings.json"),
    ],
)
def test_url_filter_applies_the_deployment_base(base, path, expected):
    assert make_environment(base).filters["url"](path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "https://example.com/x",
        "http://example.com/x",
        "#scoring",
        "mailto:a@b.c",
        # An external URL that happens to contain /assets/ must not be
        # fingerprinted: the passthrough has to run before the asset check.
        "https://cdn.example.com/assets/site.css",
    ],
)
def test_url_filter_leaves_absolute_and_anchor_links_alone(path):
    """Rewriting '#scoring' would turn an in-page jump into a navigation."""
    assert make_environment("/football-pool").filters["url"](path) == path


# -- asset fingerprinting, the cache footgun --------------------------------
# GitHub Pages pins every response to max-age=600 and offers no way to change
# it, so for ten minutes after a deploy a returning visitor can hold the old
# stylesheet against new markup. That skew looks exactly like a layout bug and
# was once reported as one.
def expected_digest(name: str) -> str:
    """Recompute the fingerprint the filter should produce for an asset.

    Derived rather than hardcoded on purpose: a hardcoded digest would have to
    be updated on every unrelated CSS edit, and a test people routinely
    regenerate without reading stops being a test.
    """
    return hashlib.sha256((ASSET_DIR / name).read_bytes()).hexdigest()[:8]


@pytest.mark.parametrize("name", ["site.css", "site.js", "favicon.svg"])
def test_every_asset_carries_its_content_hash(name):
    url = make_environment("").filters["url"](f"/assets/{name}")
    assert url == f"/assets/{name}?v={expected_digest(name)}"


def test_the_fingerprint_composes_with_the_deployment_base():
    """The stamp goes after the path, never before the prefix."""
    url = make_environment("/football-pool/").filters["url"]("/assets/site.css")
    assert url == f"/football-pool/assets/site.css?v={expected_digest('site.css')}"


def test_only_assets_are_fingerprinted():
    """Page URLs get pasted into the family group chat; keep them clean."""
    url = make_environment("").filters["url"]
    for path in ("/", "/rules/", "/entrant/brandon/", "/data/standings.json"):
        assert "?v=" not in url(path)


@pytest.mark.parametrize(
    "path",
    [
        "/assets/nope.css",  # no such file
        "/assets/fonts/",  # a directory, not a file
        "/assets/",  # the directory itself
    ],
)
def test_an_unhashable_asset_degrades_to_a_plain_url(path):
    """A deleted favicon must not take the whole scoreboard down with it."""
    url = make_environment("").filters["url"](path)
    assert url == path
    assert "?v=" not in url


def test_a_changed_asset_changes_the_url(tmp_path, monkeypatch):
    """The actual cache-busting behaviour, not merely that a hash exists."""
    assets = tmp_path / "assets"
    shutil.copytree(ASSET_DIR, assets)
    monkeypatch.setattr("football_pool.render.ASSET_DIR", assets)

    before = make_environment("").filters["url"]("/assets/site.css")

    (assets / "site.css").write_text((assets / "site.css").read_text() + "\n/* x */")
    # A fresh environment, because the digest cache is per build by design.
    after = make_environment("").filters["url"]("/assets/site.css")

    assert before != after
    assert before.split("?v=")[0] == after.split("?v=")[0]


def test_an_unchanged_asset_keeps_its_url():
    """The guard against anyone reaching for a timestamp later."""
    first = make_environment("").filters["url"]("/assets/site.css")
    second = make_environment("").filters["url"]("/assets/site.css")
    assert first == second


def test_no_root_absolute_urls_survive_a_based_build(pool, game_data, tmp_path):
    """The failure that only ever shows up in production."""
    render_site(pool, game_data, tmp_path, base="/football-pool")

    for page in tmp_path.rglob("*.html"):
        html = page.read_text()
        for attr, value in re.findall(r'(href|src)="(/[^"]*)"', html):
            assert value.startswith("/football-pool/"), (
                f"{page.name}: {attr}={value} is root-absolute and will 404 "
                f"on a project page"
            )


def test_base_tag_is_never_used(pool, game_data, tmp_path):
    """`<base href>` would silently break every in-page anchor."""
    render_site(pool, game_data, tmp_path, base="/football-pool")
    assert "<base " not in (tmp_path / "index.html").read_text()


# -- pages -------------------------------------------------------------------
def test_builds_every_expected_page(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)

    for rel in (
        "index.html",
        "rules/index.html",
        "forecast/index.html",
        "schedule/index.html",
        "teams/index.html",
        "weeks/index.html",
        "season/index.html",
        "404.html",
        "entrant/aunt-carol/index.html",
        "entrant/cousin-mike/index.html",
        "entrant/brandon/index.html",
        "data/standings.json",
    ):
        assert (tmp_path / rel).exists(), rel


def test_assets_are_copied(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    assert (tmp_path / "assets" / "site.css").exists()
    assert (tmp_path / "assets" / "site.js").exists()


def test_leaderboard_is_ordered_and_linked(pool, game_data, tmp_path):
    """Scoped to the board's own rows.

    Counting every entrant link on the page used to work because a row was the
    only place a name appeared. It is not any more — the leader tile, the
    week's best and the forecast rows all name people too, and all of them are
    links now. `.row-link` is the row's own, one per entry, in board order.
    """
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()

    order = re.findall(r'class="row-link" href="/entrant/([a-z-]+)/"', html)
    assert order[0] == "aunt-carol"  # highest scorer in 2025
    assert len(order) == 3


def test_every_entrant_page_is_reachable_and_names_its_teams(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    page = (tmp_path / "entrant" / "brandon" / "index.html").read_text()
    assert "Brandon" in page
    for team in ("ARI", "NYJ", "TEN", "CLE"):
        assert team in page


def test_an_entrants_team_cards_are_links_to_the_team_pages(pool, game_data, tmp_path):
    """The four cards under "where the points come from", not just the chips.

    The hero chips were already links; the cards are the bigger, more obvious
    target and used to be dead ends. The whole card is the anchor — it holds
    no other links, so nothing nests.
    """
    render_site(pool, game_data, tmp_path)
    page = (tmp_path / "entrant" / "cousin-mike" / "index.html").read_text()

    cards = re.findall(r'<a class="card team-card" href="/team/([A-Z]+)/"', page)
    assert sorted(cards) == sorted(["KC", "CIN", "DAL", "NO"])


def test_every_page_carries_the_two_links_off_the_site(pool, game_data, tmp_path):
    """The model the forecast runs on, and the source that builds the page.

    On every page rather than tucked in a footer somewhere: "where did this
    number come from" is a question that gets asked on whichever page the
    number is on. Both open in a new tab — unlike the Venmo link, which is an
    errand you go and run — and `rel="noopener"` goes with `target="_blank"`.
    """
    render_site(pool, game_data, tmp_path)

    for name in ("index.html", "forecast/index.html", "rules/index.html"):
        html = (tmp_path / name).read_text()
        assert f'href="{MODEL_URL}" target="_blank" rel="noopener"' in html, name
        assert f'href="{REPO_URL}" target="_blank" rel="noopener"' in html, name
        assert ">Model</a>" in html, name


def test_rules_page_renders_from_the_rules_file(pool, game_data, tmp_path):
    """Posted rules and scoring maths come from one source, so they can't drift."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "rules" / "index.html").read_text()
    assert "+3.0" in html  # division winner
    assert "+1.5" in html  # wild card
    assert "0.5 × LF" in html  # the tie policy from rules.yaml
    assert "2.60" in html  # ARI's leveling factor


def test_rules_page_posts_the_deadlines_from_the_schedule(pool, game_data, tmp_path):
    """Picks due before the first kickoff, money due by the end of week 1.

    Both dates are read off the games file rather than typed into a template,
    so they are right for whichever season is being built. The 2025 fixture
    opens Thursday Sep 4 and closes its first week on Monday Sep 8.
    """
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "rules" / "index.html").read_text()

    assert "Picks are due before kickoff" in html
    # An instant, machine-readable, so the client can show the visitor's zone —
    # with the Eastern rendering as the scripting-off text.
    assert 'datetime="2025-09-05T00:20:00+00:00"' in html
    assert "Thu, Sep 4, 8:20 PM EDT" in html
    assert "Payment is due by the end of Week" in html
    assert "Monday, September 8" in html


def test_rules_page_shows_venmo_as_a_qr_and_a_link(pool, game_data, tmp_path):
    """How to pay is on the rules page twice: a scannable code and a tappable
    link, both straight to the commissioner's Venmo profile."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "rules" / "index.html").read_text()

    assert 'href="https://venmo.com/u/Brian-Moore-4"' in html
    assert ">https://venmo.com/u/Brian-Moore-4</a>" in html  # the URL is visible text
    assert "@Brian-Moore-4 on Venmo" in html
    # The QR is a site asset, so it carries the cache-busting fingerprint.
    assert re.search(r'src="/assets/venmo-qr\.svg\?v=[0-9a-f]{8}"', html)


def test_a_pool_without_venmo_still_posts_its_deadlines(two_pools, game_data, tmp_path):
    """The friends fixture has no venmo key: deadlines render, the QR doesn't."""
    render_pools(two_pools, game_data, tmp_path, simulations=SIMS)
    html = (tmp_path / "friends" / "rules" / "index.html").read_text()

    assert "Picks are due before kickoff" in html
    assert "venmo" not in html.lower()


def test_freshness_stamps_are_machine_readable(pool, game_data, tmp_path):
    """Rendered as UTC in a datetime attribute so JS can localise them."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()
    # `data-ts` may be followed by `data-age` on the data-through stamp, which
    # is what asks the client for the "2h ago" badge beside it.
    stamps = re.findall(r'<time datetime="([^"]+)" data-ts[ >]', html)
    assert len(stamps) == 2  # data-through and site-built
    for iso in stamps:
        datetime.fromisoformat(iso)


def test_freshness_is_above_the_fold(pool, game_data, tmp_path):
    """Both stamps sit at the top of the page, not buried in the footer.

    A scoreboard that is quietly two days stale is worse than one that says so,
    and nobody scrolls to the bottom of a leaderboard to check.
    """
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()

    assert html.index("Data through") < html.index('<main')
    assert html.index("Site built") < html.index('<main')
    # The data stamp asks for an age badge; the build stamp does not need one.
    assert re.search(r'data-ts data-age>', html)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("network", "live from nflverse"),
        ("cache", "a cached copy"),
        ("fallback", "the committed snapshot"),
        # An unknown source is printed as-is rather than swallowed: a new
        # fetch outcome should show up on the page, not vanish from it.
        ("something-new", "something-new"),
    ],
)
def test_the_source_is_written_in_words(pool, games_2025, tmp_path, source, expected):
    """"fallback" means nothing to anyone who has not read the fetcher."""
    data = GameData(games_2025, 2025, NOW, None, source)
    render_site(pool, data, tmp_path)
    assert expected in (tmp_path / "index.html").read_text()


def test_timezone_picker_defaults_to_eastern(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()
    first_option = re.search(r"<select data-tz-select>\s*<option value=\"([^\"]+)\"", html)
    assert first_option.group(1) == "America/New_York"


def test_theme_toggle_is_present(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    assert "data-theme-toggle" in (tmp_path / "index.html").read_text()


# -- preseason, the state the site launches in ------------------------------
def test_preseason_builds_with_no_games_played(pool, games_2025, tmp_path):
    empty = games_2025.copy()
    empty[["played", "home_won", "away_won", "is_tie"]] = False
    data = GameData(empty, 2025, datetime.now(timezone.utc), None, "cache")

    render_site(pool, data, tmp_path)
    html = (tmp_path / "index.html").read_text()
    assert "Preseason" in html
    assert "Nothing has kicked off yet" in html
    assert "Nothing has been played yet" in (tmp_path / "season" / "index.html").read_text()


def test_weeks_and_trends_forward_to_season(pool, game_data, tmp_path):
    """A year of group-chat links points at the old pages; they must forward."""
    render_site(pool, game_data, tmp_path)
    for rel in ("weeks", "trends"):
        html = (tmp_path / rel / "index.html").read_text()
        assert 'url=/season/' in html


def test_a_pool_with_a_single_entrant_builds(make_season, game_data, tmp_path):
    solo = make_season([{"name": "Solo", "teams": ["KC", "SEA", "DAL", "NE"]}], year=2025)
    render_site(solo, game_data, tmp_path)
    assert "Solo" in (tmp_path / "index.html").read_text()


# -- mid-season -------------------------------------------------------------
def test_mid_season_shows_the_current_week(pool, mid_season, tmp_path):
    render_site(pool, mid_season, tmp_path)
    assert "Week 11" in (tmp_path / "index.html").read_text()


def test_weeks_page_has_a_column_per_played_week(pool, mid_season, tmp_path):
    render_site(pool, mid_season, tmp_path)
    html = (tmp_path / "season" / "index.html").read_text()
    header = re.search(r"<thead>.*?</thead>", html, re.S).group(0)
    # Matched on the heading's text rather than on its attributes, which now
    # also carry the sort direction the column opens in.
    assert len(re.findall(r"<th[^>]*>(\d+)</th>", header)) == 11


# -- the json sidecar -------------------------------------------------------
def test_standings_json_is_valid_and_complete(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    payload = json.loads((tmp_path / "data" / "standings.json").read_text())

    assert payload["season"] == 2025
    assert len(payload["entrants"]) == 3
    assert payload["entrants"][0]["rank"] == 1
    # Rendered markup does not belong in the data file.
    assert "spark" not in payload["entrants"][0]


def test_context_totals_agree_with_the_rendered_page(pool, game_data, tmp_path):
    ctx = build_context(pool, game_data)
    render_site(pool, game_data, tmp_path)
    payload = json.loads((tmp_path / "data" / "standings.json").read_text())

    for row in payload["entrants"]:
        expected = float(ctx.outlook.loc[ctx.outlook["name"] == row["name"], "banked"].iloc[0])
        assert row["banked"] == pytest.approx(expected)


# -- rebuild stability ------------------------------------------------------
def test_rebuilding_is_deterministic(pool, mid_season, tmp_path):
    """A day with no new games must not produce a diff."""
    a, b = tmp_path / "a", tmp_path / "b"
    render_site(pool, mid_season, a)
    render_site(pool, mid_season, b)

    for page in sorted(a.rglob("*.html")):
        other = b / page.relative_to(a)
        # The build timestamp is the only thing allowed to differ.
        strip = lambda s: re.sub(r'<time datetime="[^"]+" data-ts>[^<]+</time>', "", s)
        assert strip(page.read_text()) == strip(other.read_text()), page.name


def test_playoff_phase_is_labelled(pool, games_2025, tmp_path):
    """Regular season done, bracket still running."""
    g = games_2025.copy()
    g.loc[g["game_type"].isin({"DIV", "CON", "SB"}), "played"] = False
    data = GameData(g, 2025, datetime.now(timezone.utc), None, "cache")

    render_site(pool, data, tmp_path)
    assert "Playoffs" in (tmp_path / "index.html").read_text()


def test_final_phase_is_labelled(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    assert "Final" in (tmp_path / "index.html").read_text()


def test_money_filter_hides_zero_and_missing(pool):
    """An entrant out of the money shows nothing, not "$0"."""
    money = make_environment().filters["money"]
    assert money(0) == ""
    assert money(None) == ""
    assert money(37.5) == "$38"


def test_points_filter_pads_and_handles_missing(pool):
    points = make_environment().filters["points"]
    assert points(3.5) == "3.50"
    assert points(None) == "—"


def test_assets_missing_does_not_break_the_build(pool, game_data, tmp_path, monkeypatch):
    """Rendering must still work if the asset directory is absent."""
    out = tmp_path / "out"
    monkeypatch.setattr("football_pool.render.ASSET_DIR", tmp_path / "nope")
    written = render_site(pool, game_data, out)

    assert (out / "index.html").exists()
    assert not (out / "assets").exists()
    assert not any(p.relative_to(out).parts[0] == "assets" for p in written)


def test_a_removed_entrant_stops_being_published(make_season, game_data, tmp_path):
    """Their page must not stay live and reachable after they leave the pool."""
    before = make_season(
        [
            {"name": "Stays", "teams": ["KC", "SEA", "DAL", "NE"]},
            {"name": "Leaves", "teams": ["ARI", "BUF", "GB", "MIA"]},
        ],
        year=2025,
    )
    render_site(before, game_data, tmp_path)
    assert (tmp_path / "entrant" / "leaves" / "index.html").exists()

    after = make_season([{"name": "Stays", "teams": ["KC", "SEA", "DAL", "NE"]}], year=2025)
    render_site(after, game_data, tmp_path)
    assert (tmp_path / "entrant" / "stays" / "index.html").exists()
    assert not (tmp_path / "entrant" / "leaves").exists()


def test_a_broken_model_does_not_take_the_site_down(pool, mid_season, tmp_path, monkeypatch):
    """Actual standings are the point; a projection failure must not cost them."""
    def boom(*a, **kw):
        raise RuntimeError("simulation exploded")

    monkeypatch.setattr("football_pool.render.project", boom)
    with pytest.warns(RuntimeWarning, match="projections unavailable"):
        render_site(pool, mid_season, tmp_path)

    html = (tmp_path / "index.html").read_text()
    assert "Standings" in html
    assert "Projected finish" not in html


def test_projections_appear_when_available(pool, mid_season, tmp_path):
    """A summary on the standings page, the full table on /forecast/.

    The standings page is a scoreboard — what has happened — so it carries the
    headline only, and the distributional detail lives on its own page.
    """
    render_site(pool, mid_season, tmp_path, simulations=200)
    index = (tmp_path / "index.html").read_text()
    # The teaser says which of the two questions its percentage answers, which
    # a bare "projected finish" never did.
    assert "Most likely to win" in index
    assert "modelled" in index

    forecast = (tmp_path / "forecast" / "index.html").read_text()
    assert "Chance of winning" in forecast
    assert "Chance of cashing" in forecast


def test_projections_are_absent_once_the_season_ends(pool, game_data, tmp_path):
    """Nothing left to simulate, so the panels are dropped rather than faked."""
    render_site(pool, game_data, tmp_path)
    assert "Most likely to win" not in (tmp_path / "index.html").read_text()


def test_an_entrant_missing_from_the_model_is_tolerated(pool, mid_season, monkeypatch):
    """A name mismatch must yield no projection, not a crash."""
    from football_pool import render as render_mod

    ctx = render_mod.build_context(pool, mid_season, simulations=200)
    assert render_mod._projection_for(ctx, "Nobody At All") is None


def test_history_and_render_agree_on_week_count(pool, mid_season):
    ctx = build_context(pool, mid_season)
    assert ctx.history.attrs["weeks"] == list(range(1, 12))
    assert weekly_frame(pool, mid_season.games).attrs["weeks"] == ctx.history.attrs["weeks"]


# -- theme, identity and the morph -------------------------------------------
def test_the_markup_itself_is_dark(season, game_data, tmp_path):
    """Dark is the default in the document, not merely in the stylesheet.

    Anything that reads the page before CSS lands — or with scripting off —
    must already be on the dark theme rather than flashing light first.
    """
    render_site(season, game_data, tmp_path)
    assert 'data-theme="dark"' in (tmp_path / "index.html").read_text()


def test_the_row_and_the_hero_share_a_transition_name(season, game_data, tmp_path):
    """This pairing is what makes clicking a row morph instead of cross-fade.

    The names live in two separate templates, so nothing but a test notices
    when one of them is renamed and the effect silently degrades.
    """
    render_site(season, game_data, tmp_path)
    index = (tmp_path / "index.html").read_text()

    for entrant in season.entrants:
        slug = _slug_of(tmp_path, entrant.name)
        page = (tmp_path / "entrant" / slug / "index.html").read_text()
        for name in (f"name-{slug}", f"total-{slug}"):
            assert f"view-transition-name: {name}" in index, f"{name} missing from the board"
            assert f"view-transition-name: {name}" in page, f"{name} missing from the hero"


def test_transition_names_are_unique_within_a_page(season, game_data, tmp_path):
    """A duplicate name makes the browser drop the transition for both elements."""
    render_site(season, game_data, tmp_path)
    names = re.findall(r"view-transition-name: ([\w-]+)", (tmp_path / "index.html").read_text())
    assert len(names) == len(set(names))


def _real_pages(written):
    """Every rendered page, minus the chrome-less forwarding stubs."""
    for page in written:
        if page.suffix != ".html":
            continue
        text = page.read_text()
        if 'http-equiv="refresh"' in text:
            continue
        yield page, text


def test_every_page_offers_the_identity_picker(season, game_data, tmp_path):
    written = render_site(season, game_data, tmp_path)
    for page, text in _real_pages(written):
        assert "data-me-select" in text, page


def test_rows_carry_the_slug_the_picker_matches_on(season, game_data, tmp_path):
    """The picker's option values and the rows' data-slug must be the same set."""
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()

    row_slugs = set(re.findall(r'class="row[^"]*"\s+style="[^"]*"\s+data-slug="([\w-]+)"', html))
    # Scope to the identity picker: the time zone control is a <select> too, and
    # matching every <option> on the page would sweep up "UTC".
    picker = re.search(r"<select data-me-select>(.*?)</select>", html, re.S).group(1)
    option_slugs = set(re.findall(r'<option value="([\w-]+)">', picker))
    assert row_slugs
    assert row_slugs == option_slugs


# -- team colours -------------------------------------------------------------
def test_team_chips_wear_their_club_colours(season, game_data, tmp_path):
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()
    assert "--team-bg:" in html and "--team-fg:" in html and "--team-edge:" in html


def test_every_chip_that_names_a_team_is_coloured(season, game_data, tmp_path):
    """A chip with no colour block would render as an unexplained grey outlier."""
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "teams" / "index.html").read_text()

    # The chips on this page became links when teams got pages of their own,
    # so the href sits between the class and the style.
    chips = re.findall(
        r'<a class="team-chip[^"]*"\s*\n?\s*href="[^"]*"\s*\n?\s*'
        r'style="([^"]*)">(?:<img[^>]*>)?([A-Z]{2,3})</a>',
        html,
    )
    assert len(chips) >= 32
    for style, team in chips:
        assert "--team-bg:" in style, f"{team} chip has no colour"


# -- sortable tables ----------------------------------------------------------
def test_the_teams_table_is_sortable_with_real_sort_keys(season, game_data, tmp_path):
    """Every sortable column needs a key that sorts correctly as a number.

    Displayed text would sort "10-2" before "3-1" and put unseeded teams above
    the top seed, so the sort keys are emitted separately.
    """
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "teams" / "index.html").read_text()

    assert html.count("data-sort") == 6
    assert 'class="table-scroll is-tall"' in html
    # An unseeded team sorts to the bottom rather than sorting as empty.
    assert 'data-value="99"' in html


def test_the_seed_sort_key_orders_playoff_teams_first(season, game_data, tmp_path):
    """Seeds 1..7 must come before the 99 that stands in for "did not qualify"."""
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "teams" / "index.html").read_text()
    seeds = [int(v) for v in re.findall(r'<td data-value="(\d+)">\s*\n?\s*(?:<span class="badge money">|—)', html)]
    assert sorted(s for s in seeds if s != 99)[:1] == [1]
    assert 99 in seeds


# -- the comparison chart -----------------------------------------------------
def test_the_compare_chart_offers_every_entrant(season, game_data, tmp_path):
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "season" / "index.html").read_text()

    picks = set(re.findall(r'data-pick="([\w-]+)"', html))
    lines = set(re.findall(r'<polyline class="cmp-line" data-entrant="([\w-]+)"', html))
    assert picks
    assert picks == lines, "a name you can pick must have a line to light up"


def test_the_compare_chart_ships_unpicked(season, game_data, tmp_path):
    """The server does not choose for the viewer; the browser does."""
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "season" / "index.html").read_text()
    assert "is-picked" not in html
    assert html.count("data-compare>") == 2  # points and rank


def test_the_compare_chart_is_absent_before_any_games(season, tmp_path, games_2025):
    """Nothing to compare in the preseason, so it must not render an empty frame."""
    g = games_2025.copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    preseason = GameData(g, 2025, datetime.now(timezone.utc), None, "cache")

    render_site(season, preseason, tmp_path)
    html = (tmp_path / "season" / "index.html").read_text()
    assert "data-pick=" not in html


def _slug_of(out_dir: Path, name: str) -> str:
    """Find the slug the site actually generated for an entrant."""
    data = json.loads((out_dir / "data" / "standings.json").read_text())
    return next(e["slug"] for e in data["entrants"] if e["name"] == name)


# -- preseason honesty --------------------------------------------------------
def test_no_playoff_seeds_are_shown_before_any_game(season, tmp_path, games_2025):
    """The Teams page must not claim a playoff field in the preseason.

    Every club is 0-0, so the tiebreaker ladder exhausted and fell through to
    its alphabetical coin-toss fallback — and the page printed the result as
    fourteen seeded teams, with the one seeds going to whoever came first in
    the alphabet. This is the page-level guard for that.
    """
    g = games_2025.copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    preseason = GameData(g, 2025, datetime.now(timezone.utc), None, "cache")

    render_site(season, preseason, tmp_path)
    html = (tmp_path / "teams" / "index.html").read_text()

    seeded = re.findall(r'<span class="badge money">(\d)</span>', html)
    assert seeded == [], f"{len(seeded)} teams shown as seeded before kickoff"
    # All 32 rows sort to the bottom of the seed column instead.
    assert html.count('<td data-value="99">') == 32


def test_entrant_cards_omit_the_seed_before_any_game(season, tmp_path, games_2025):
    g = games_2025.copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    preseason = GameData(g, 2025, datetime.now(timezone.utc), None, "cache")

    written = render_site(season, preseason, tmp_path)
    for page in (p for p in written if p.parent.parent.name == "entrant"):
        assert "seed " not in page.read_text()


def test_seeds_return_once_the_season_is_under_way(season, mid_season, tmp_path):
    """The projection is a feature — this must not have thrown it away."""
    render_site(season, mid_season, tmp_path)
    html = (tmp_path / "teams" / "index.html").read_text()
    assert len(re.findall(r'<span class="badge money">(\d)</span>', html)) == 14


# -- fingerprints in the built site -------------------------------------------
ASSET_URL_RE = re.compile(r'(?:href|src)="([^"]*/assets/[^"]*)"')


def test_every_asset_url_on_every_page_is_fingerprinted(season, game_data, tmp_path):
    """Guards assets that do not exist yet.

    The point of doing this inside the one filter every URL already passes
    through is that a new asset cannot forget to opt in — this asserts it.
    """
    render_site(season, game_data, tmp_path, base="/football-pool")

    seen = 0
    for page in tmp_path.rglob("*.html"):
        for url in ASSET_URL_RE.findall(page.read_text()):
            seen += 1
            assert re.search(r"\?v=[0-9a-f]{8}$", url), f"{page.name}: {url}"
    assert seen >= 3, "expected at least the stylesheet, the script and the favicon"


def test_the_fingerprint_matches_the_bytes_that_shipped(season, game_data, tmp_path):
    """The URL the browser asks for must name the file that was published.

    This is the real invariant. It is also what would catch a minifier being
    slipped in between hashing the source and copying it to the output.
    """
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()

    checked = 0
    for url in ASSET_URL_RE.findall(html):
        path, _, stamp = url.partition("?v=")
        shipped = tmp_path / path.lstrip("/")
        assert shipped.is_file(), f"{url} does not exist in the output"
        assert stamp == hashlib.sha256(shipped.read_bytes()).hexdigest()[:8]
        checked += 1
    assert checked >= 3


def test_page_links_are_never_fingerprinted(season, game_data, tmp_path):
    """A stamp on /entrant/x/ would break every in-page link regex, and look daft."""
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()

    links = [u for u in re.findall(r'href="(/[^"]*)"', html) if "/assets/" not in u]
    assert links, "expected at least the nav links"
    for url in links:
        assert "?v=" not in url, url


def test_the_stylesheet_still_finds_its_fonts(season, game_data, tmp_path):
    """A relative url() inside the CSS resolves against the path, not the query.

    RFC 3986 §5.3: a non-empty relative reference does not inherit the base's
    query, so `fonts/x.woff2` resolves correctly under `site.css?v=...`. This is
    also the regression guard against anyone rewriting the CSS to rename files.
    """
    render_site(season, game_data, tmp_path)
    css = (tmp_path / "assets" / "site.css").read_text()

    assert "url('fonts/big-shoulders.woff2')" in css
    assert sorted(p.name for p in (tmp_path / "assets" / "fonts").glob("*.woff2"))


def test_the_ci_contract_holds(two_pools, game_data, tmp_path):
    """Mirrors the greps in ci.yml so this breaks in pytest, not a required check."""
    root = tmp_path / "root"
    project = tmp_path / "project"
    render_pools(two_pools, game_data, root, base="", simulations=SIMS)
    render_pools(two_pools, game_data, project, base="/football-pool", simulations=SIMS)

    assert re.search(
        r'href="/assets/site\.css\?v=[0-9a-f]{8}"', (root / "index.html").read_text()
    )
    assert re.search(
        r'href="/football-pool/assets/site\.css\?v=[0-9a-f]{8}"',
        (project / "index.html").read_text(),
    )
    assert (project / "rules" / "index.html").exists()
    assert (project / "schedule" / "index.html").exists()
    assert (project / "data" / "standings.json").exists()

    # The second pool is a whole site of its own, one level down...
    friends = project / "friends"
    assert (friends / "index.html").exists()
    assert (friends / "data" / "standings.json").exists()
    assert (friends / "rules" / "index.html").exists()
    # ...but its assets come from the site root, and exist only there.
    assert re.search(
        r'href="/football-pool/assets/site\.css\?v=[0-9a-f]{8}"',
        (friends / "index.html").read_text(),
    )
    assert not (friends / "assets").exists()
    # The pools are sealed off from each other, and the root pool did not move.
    assert 'href="/football-pool/friends/' not in (project / "index.html").read_text()
    assert 'href="/football-pool/"' not in (friends / "index.html").read_text()
    # And the root build too, where an empty prefix hides a bug differently.
    assert re.search(
        r'href="/assets/site\.css\?v=[0-9a-f]{8}"',
        (root / "friends" / "index.html").read_text(),
    )


# -- viewer preferences sit at the top ----------------------------------------
def test_the_viewer_controls_come_before_the_content(season, game_data, tmp_path):
    """Both settings change what you are looking at, so they precede it.

    They used to live in the footer, where nobody scrolled to find them. This
    pins the position rather than merely their existence — the previous test
    passed perfectly well while they were invisible at the bottom of the page.
    """
    written = render_site(season, game_data, tmp_path)

    for page, html in _real_pages(written):
        main_at = html.index("<main")
        assert html.index("data-me-select") < main_at, page
        assert html.index("data-tz-select") < main_at, page
        assert html.index('class="viewer-bar"') < main_at, page


def test_the_controls_appear_exactly_once(season, game_data, tmp_path):
    """A duplicate would silently break the wiring.

    initMe and initTimeZone both use querySelector, so a second copy left
    behind in the footer would never be wired up and would sit there showing
    a stale value.
    """
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()

    assert html.count("data-me-select") == 1
    assert html.count("data-tz-select") == 1


def test_the_stamps_are_at_the_top_and_only_at_the_top(season, game_data, tmp_path):
    """They used to sit in the footer, behind a full page of leaderboard.

    How old the numbers are is the one caveat that changes how you read
    everything above it, so it belongs before the numbers rather than after
    them — and printed once, because two copies of a timestamp is an invitation
    to have them disagree.
    """
    render_site(season, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()
    head, footer = html.split("<footer")

    assert "Data through" in head.split("<main")[0]
    assert "Site built" in head.split("<main")[0]
    assert "Data through" not in footer
    assert len(re.findall(r"<time datetime=", html)) == 2


def test_the_footer_says_how_the_results_were_fetched(season, game_data, tmp_path):
    """What is left down there is provenance, which is reference, not caveat."""
    render_site(season, game_data, tmp_path)
    footer = (tmp_path / "index.html").read_text().split("<footer")[1]
    assert "live from nflverse" in footer


# -- the forecast page --------------------------------------------------------
def test_the_bracket_is_a_week_of_the_schedule(pool, game_data, tmp_path):
    """So the switcher, `:target` and the back button all work on it for free.

    A separate page would need its own nav entry, its own URL scheme and its
    own answer to "which week am I on". It is a section like every other week,
    and the only new markup is one more link on the end of the switcher.
    """
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert 'id="bracket"' in html
    assert 'href="#bracket"' in html
    # Thirteen games: three, two, one a conference, then one.
    assert html.count("data-tie=") == 13
    # And it is never what the page opens on — the season being played is.
    assert not re.search(r'class="week bracket-week[^"]*is-default', html)


def test_a_bracket_before_kickoff_says_what_each_slot_is_waiting_for(
    pool, preseason_data, tmp_path
):
    """No game played means no seeds, and the page says so rather than guessing."""
    render_site(pool, preseason_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert "Nothing seeded yet" in html
    # A phrase that does not cross the template's own line wrap.
    assert "empty bracket than that" in html
    for slot in ("2 seed", "7 seed", "Wild Card winner", "Divisional winner",
                 "AFC champion", "NFC champion"):
        assert slot in html, slot
    # Nothing is dressed up as a fixture.
    assert html.count('class="tie is-open"') == 13


def test_a_finished_bracket_carries_its_results(pool, game_data, tmp_path):
    """Scores, and which side won — the same colours a played game gets."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert "Seeded and settled" in html
    assert html.count('class="tie is-final"') == 13
    assert html.count('class="tie-side won"') == 13
    assert 'class="tie is-open"' not in html


def test_every_bracket_side_says_what_winning_it_pays(pool, preseason_data, game_data):
    """Which is the only reason a pool site should draw a bracket at all.

    The wild-card host is the case worth asserting: the bonus rewards the
    upset, so the host is playing for nothing, and a bracket that quietly
    printed a stake there would be wrong about the one round people ask about.
    """
    ctx = build_context(pool, preseason_data)
    built = _bracket(ctx)
    wild_card = next(r for r in built["rounds"] if r["round"] == "WC")

    # Nothing is seeded preseason, so stakes are unknown — the shape still is.
    assert all(g["home"]["stake"] is None for g in wild_card["games"])

    # With a seeded field, the host of a wild-card game plays for nothing.
    seeded = build_context(pool, game_data)
    for game in next(r for r in _bracket(seeded)["rounds"] if r["round"] == "WC")["games"]:
        assert game["home"]["stake"] == 0.0
        assert game["away"]["stake"] > 0.0

    # And in every later round both sides are playing for something.
    for code in ("DIV", "CON", "SB"):
        for game in next(r for r in _bracket(seeded)["rounds"] if r["round"] == code)["games"]:
            assert game["home"]["stake"] > 0.0
            assert game["away"]["stake"] > 0.0


def test_the_bracket_names_only_this_pool(two_pools, game_data, tmp_path):
    """The teams are the league's; the people beside them are the pool's."""
    render_pools(two_pools, game_data, tmp_path, simulations=SIMS)

    friends = (tmp_path / "friends" / "schedule" / "index.html").read_text()
    root = (tmp_path / "schedule" / "index.html").read_text()

    assert 'id="bracket"' in friends
    assert "Cousin Mike" not in friends
    assert "Priya" not in root


def test_the_switcher_calls_january_playoffs(pool, game_data, tmp_path):
    """The word on the switcher is the one people actually say.

    The id stays `bracket` — a season of sent links points at it — but nothing
    a reader sees calls it that.
    """
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert re.search(r'class="to-bracket"[^>]*>Playoffs</a>', html)
    assert 'href="#bracket"' in html
    assert ">Bracket</a>" not in html


def test_the_bracket_converges_on_the_super_bowl(pool, game_data, tmp_path):
    """Two conference wings of six games each, and the one game in the middle.

    The tournament shape, not four lists: the drawing only reads as a bracket
    because each conference fights toward the centre.
    """
    ctx = build_context(pool, game_data)
    built = _bracket(ctx)

    assert [w["conference"] for w in built["wings"]] == ["AFC", "NFC"]
    for wing in built["wings"]:
        assert [r["round"] for r in wing["rounds"]] == ["WC", "DIV", "CON"]
        assert sum(len(r["games"]) for r in wing["rounds"]) == 6
        assert all(
            g["conference"] == wing["conference"]
            for r in wing["rounds"]
            for g in r["games"]
        )
    assert built["super_bowl"]["round"] == "SB"

    # And the page draws that shape: a wing per conference, the Super Bowl
    # between them, thirteen ties among the three.
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()
    assert 'data-conf="AFC"' in html
    assert 'data-conf="NFC"' in html
    assert html.count('class="bracket-center"') == 1


def test_a_played_super_bowl_crowns_a_champion(pool, game_data, preseason_data, tmp_path):
    """One team out of fourteen ends the season happy, and the middle says so.

    Only a played Super Bowl gets this: a projected champion would be the
    exact confident-looking lie the empty preseason bracket exists to avoid.
    """
    assert _bracket(build_context(pool, game_data))["champion"]["team"]
    assert _bracket(build_context(pool, preseason_data))["champion"] is None

    render_site(pool, game_data, tmp_path / "february")
    html = (tmp_path / "february" / "schedule" / "index.html").read_text()
    assert 'class="champ"' in html
    assert "World champions" in html

    render_site(pool, preseason_data, tmp_path / "august")
    html = (tmp_path / "august" / "schedule" / "index.html").read_text()
    assert 'class="champ"' not in html


def test_the_forecast_page_carries_all_three_charts(pool, mid_season, tmp_path):
    render_site(pool, mid_season, tmp_path, simulations=200)
    html = (tmp_path / "forecast" / "index.html").read_text()

    assert 'class="finish"' in html  # finishing-place bars
    assert 'class="ridge"' in html  # score distributions
    assert 'class="heat"' in html  # head to head
    assert "modelled" in html


def test_the_forecast_ships_both_head_to_head_grids(pool, mid_season, tmp_path):
    """Drawn at build time, both of them, and the picker only chooses one.

    Neither grid is computed on the client: the numbers are the model's in
    either view, there is no arithmetic to get wrong twice, and with scripting
    off the page still shows the finishing one.
    """
    render_site(pool, mid_season, tmp_path, simulations=200)
    html = (tmp_path / "forecast" / "index.html").read_text()

    assert html.count('class="heat"') == 2
    assert 'data-heat-grid="order"' in html
    assert 'data-heat-grid="money"' in html
    assert "finishes above these" in html
    assert "out-earns these" in html
    # The money grid is the hidden one, so no-JS gets the finishing order.
    assert re.search(r'data-heat-grid="money" hidden', html)
    assert not re.search(r'data-heat-grid="order" hidden', html)
    # And the control that swaps them, with a note for each.
    assert "data-heat-view" in html
    assert 'data-heat-note="order"' in html
    assert 'data-heat-note="money" hidden' in html


def test_the_two_grids_carry_the_odds_each_one_is_about(pool, mid_season, tmp_path):
    """Outright is winning under one grid and being paid at all under the other.

    A pairwise number needs the outright one beside it or it misleads, and
    which outright number that is depends on which question the grid is
    asking. The odds ride on the axis labels, so there are 2n of them per grid.
    """
    ctx = build_context(pool, mid_season, simulations=200)
    forecast = _forecast(ctx)
    by_name = ctx.projections.entrants.set_index("name")
    order = forecast["order"]

    def odds(grid):
        return re.findall(r'class="heat-head heat-row" data-r="\d+" data-win="(\d+)"', grid)

    assert odds(forecast["heatmap"]) == [
        f"{by_name.loc[n, 'p_first'] * 100:.0f}" for n in order
    ]
    assert odds(forecast["money_heatmap"]) == [
        f"{by_name.loc[n, 'p_cash'] * 100:.0f}" for n in order
    ]


def test_the_forecast_counts_the_places_that_actually_pay(make_season, mid_season, tmp_path):
    """Which is what decides how often two entrants are level on money.

    A pool smaller than its own payout ladder cannot reach the bottom of it, so
    the page says how many places the pot really reaches rather than repeating
    the three tiers the pool file happens to declare. Two entrants, three
    tiers: two places pay, and the money grid's note says two.
    """
    duo = make_season(
        [
            {"name": "Aunt Carol", "teams": ["SEA", "NE", "PHI", "LAR"]},
            {"name": "Brandon", "teams": ["ARI", "NYJ", "TEN", "CLE"]},
        ],
        year=2025,
    )
    assert len(duo.payouts) == 3

    ctx = build_context(duo, mid_season, simulations=200)
    assert _forecast(ctx)["paid_places"] == 2

    render_site(duo, mid_season, tmp_path, simulations=200)
    assert "pays 2 places" in (tmp_path / "forecast" / "index.html").read_text()


def test_the_forecast_page_has_a_row_per_entrant(pool, mid_season, tmp_path):
    render_site(pool, mid_season, tmp_path, simulations=200)
    html = (tmp_path / "forecast" / "index.html").read_text()

    slugs = re.findall(r'class="forecast-row"[^>]*data-slug="([\w-]+)"', html)
    assert len(slugs) == len(pool.entrants)
    assert len(set(slugs)) == len(slugs)


def test_the_forecast_is_ordered_by_chance_of_winning(pool, mid_season, tmp_path):
    """The model's own ranking, not the current standings — they differ."""
    ctx = build_context(pool, mid_season, simulations=200)
    render_site(pool, mid_season, tmp_path, simulations=200)
    html = (tmp_path / "forecast" / "index.html").read_text()

    shown = re.findall(r'class="forecast-row"[^>]*data-slug="([\w-]+)"', html)
    expected = (
        ctx.projections.entrants.sort_values("p_first", ascending=False)["slug"].tolist()
    )
    assert shown == expected


def test_the_forecast_page_names_what_the_ratings_came_from(pool, mid_season, tmp_path):
    """Two different fits can produce this page, and they answer subtly
    different questions — describing one while running the other would be the
    quietest way for the site to mislead."""
    render_site(pool, mid_season, tmp_path, simulations=200)
    without = (tmp_path / "forecast" / "index.html").read_text()

    lined = GameData(
        mid_season.games.assign(spread_line=2.5),
        2025,
        datetime.now(timezone.utc),
        None,
        "cache",
    )
    render_site(pool, lined, tmp_path, simulations=200)
    with_lines = (tmp_path / "forecast" / "index.html").read_text()

    assert "preseason win totals" in without
    assert "betting lines" not in without
    assert "betting lines" in with_lines
    assert "preseason win totals" not in with_lines


def test_the_forecast_tab_is_in_the_nav_on_every_page(pool, mid_season, tmp_path):
    written = render_site(pool, mid_season, tmp_path, simulations=200)
    for page, text in _real_pages(written):
        assert "/forecast/" in text, page


def test_the_forecast_page_explains_itself_when_there_is_nothing_to_say(
    pool, game_data, tmp_path
):
    """Once the bracket starts there is nothing left to simulate."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "forecast" / "index.html").read_text()

    assert 'class="finish"' not in html
    assert "The season is over" in html


def test_the_standings_page_links_to_the_full_forecast(pool, mid_season, tmp_path):
    """The scoreboard keeps a headline; the distributions live on their own page."""
    render_site(pool, mid_season, tmp_path, simulations=200)
    index = (tmp_path / "index.html").read_text()

    assert 'class="finish"' in index  # the summary bars
    assert 'class="ridge"' not in index  # but not the full picture
    assert 'href="/forecast/"' in index


def test_every_game_carries_what_it_is_worth_to_everybody(pool, game_data, tmp_path):
    """The collapsed row shows the reader their own number. The argument in the
    group chat is about everyone else's, so the panel names all of them."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert html.count('class="game-more"') == len(game_data.games)
    # The team named in the fact is a link to that team, like every other place
    # this site writes a three-letter code.
    assert 'If <a href="/team/KC/">KC</a> win' in html
    assert "On the table for" in html
    # Both sides priced, whoever is holding them.
    assert "to nobody here" in html
    # And the people named in the panel are links, not the one place on the
    # page where a name is only a name.
    assert re.search(
        r'<dd>[^<]*<a class="owner" href="/entrant/[a-z-]+/" data-slug=', html
    )


def test_a_game_panel_is_open_in_the_markup_and_folded_by_the_client(
    pool, game_data, tmp_path
):
    """The one rule this site has about hidden things.

    Nothing is ever invisible without JavaScript, so the panel ships open and
    the stylesheet folds it away only when `data-js` says there is a client
    that can open it again. Set before first paint, or the panels would render
    open and then snap shut.
    """
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert "dataset.js = 'on'" in html
    assert not re.search(r'class="game-more"[^>]*hidden', html)
    assert 'aria-expanded="false"' in html
    assert re.search(r'aria-controls="more-[^"]+"', html)


def test_the_schedule_can_be_cut_to_the_games_the_pool_is_in(pool, game_data, tmp_path):
    """A third of any week is games nobody here holds."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert "data-slate-toggle" in html
    assert "Pool games only" in html
    # The rows the filter acts on are marked by the build, not found by the
    # client — `is-idle` already existed to dim them.
    assert 'class="game is-idle' in html


def test_a_week_the_pool_has_no_side_in_says_so_rather_than_going_blank(
    make_season, game_data, tmp_path
):
    """With the filter on, a week of nothing would otherwise look broken.

    January is where this actually happens: four teams that all missed the
    playoffs leaves the pool with no side in any of the four postseason weeks,
    and that is a real state a real pool spends a month in.
    """
    watching = make_season(
        [{"name": "Solo", "teams": ["ARI", "CLE", "NYJ", "TEN"]}], year=2025
    )
    schedule = _schedule(build_context(watching, game_data))
    blank = [w for w in schedule["weeks"] if not w["pool_games"]]
    assert blank, "the fixture should leave this pool out of the postseason"

    render_site(watching, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert html.count('class="empty slate-empty"') == len(blank)
    assert "Nobody here holds a side in" in html


def test_every_team_gets_a_page(pool, game_data, tmp_path):
    """All 32, not only the ones somebody picked.

    A team nobody holds is exactly the team you want to read about when you are
    deciding whether to be annoyed that nobody has it.
    """
    render_site(pool, game_data, tmp_path)

    for team in pool.teams:
        page = tmp_path / "team" / team / "index.html"
        assert page.exists(), team
        assert team in page.read_text()


def test_a_team_page_lists_that_team_and_nobody_else(pool, game_data, tmp_path):
    """Every game they play, in order, and none that they do not."""
    ctx = build_context(pool, game_data)
    page = _team_page(ctx, "KC")

    theirs = ctx.games[
        (ctx.games["home_team"] == "KC") | (ctx.games["away_team"] == "KC")
    ]
    assert len(page["games"]) == len(theirs)
    for g in page["games"]:
        assert "KC" in (g["home"]["team"], g["away"]["team"])
    # Ordered by week, then kickoff — a season reads down the page.
    weeks = [g["week"] for g in page["games"]]
    assert weeks == sorted(weeks)


def test_a_team_page_names_the_bye_where_it_falls(pool, game_data, tmp_path):
    """A list that jumps from week 5 to week 7 has said nothing about week 6."""
    ctx = build_context(pool, game_data)
    page = _team_page(ctx, "KC")

    played_weeks = {g["week"] for g in page["games"]}
    reg = ctx.games[ctx.games["game_type"] == "REG"]
    missing = set(reg["week"].astype(int)) - played_weeks

    byes = [r for r in page["season"] if r.get("bye")]
    assert {b["week"] for b in byes} == missing
    assert byes, "the fixture season has a bye somewhere"
    # The bye sits in week order with the games rather than at the end.
    order = [r["week"] for r in page["season"]]
    assert order == sorted(order)

    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "team" / "KC" / "index.html").read_text()
    assert "game-bye" in html


def test_a_team_page_says_what_it_was_worth_to_each_owner(pool, game_data, tmp_path):
    """The points are one number; the share of a total is not.

    That is the whole reason the block exists — the same 12 points is a quarter
    of one entry and a twentieth of another.
    """
    ctx = build_context(pool, game_data)
    # Cousin Mike holds KC in the three-way fixture; Aunt Carol does not.
    page = _team_page(ctx, "KC")

    assert [o["name"] for o in page["owners"]] == ["Cousin Mike"]
    owner = page["owners"][0]
    assert owner["points"] == pytest.approx(page["points"])
    assert owner["share"] == pytest.approx(owner["points"] / owner["banked"])
    assert 0.0 < owner["share"] <= 1.0


def test_a_team_nobody_holds_still_has_a_page(pool, game_data, tmp_path):
    """And says so, rather than rendering an empty block."""
    ctx = build_context(pool, game_data)
    held = {t for e in pool.entrants for t in e.teams}
    spare = next(t for t in pool.teams if t not in held)

    assert _team_page(ctx, spare)["owners"] == []

    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "team" / spare / "index.html").read_text()
    assert "Nobody in this pool holds" in html


def test_team_pages_are_scoped_to_their_own_pool(two_pools, game_data, tmp_path):
    """Same football, different people — and the people are the pool's own.

    The football on a team page is identical in both pools, so the owners block
    is the entire difference and the entire risk: one family name on a friends
    page is a hole straight through the wall between them.
    """
    render_pools(two_pools, game_data, tmp_path, simulations=SIMS)

    root = (tmp_path / "team" / "KC" / "index.html").read_text()
    friends = (tmp_path / "friends" / "team" / "KC" / "index.html").read_text()

    assert "Cousin Mike" in root and "Priya" not in root
    assert "Priya" in friends and "Cousin Mike" not in friends
    assert 'href="/friends/entrant/priya/"' in friends


def test_a_removed_team_page_does_not_survive_a_rebuild(pool, game_data, tmp_path):
    """Team paths come from rules.yaml, so they can change under a rebuild."""
    render_site(pool, game_data, tmp_path)
    stale = tmp_path / "team" / "XYZ"
    stale.mkdir(parents=True)
    (stale / "index.html").write_text("a team that no longer exists")

    render_site(pool, game_data, tmp_path)
    assert not stale.exists()


def test_a_chip_is_a_link_to_that_team_everywhere_it_can_be(pool, game_data, tmp_path):
    """A team is one object on this site, and it goes to one place.

    The board used to be the exception, because its rows were themselves links
    to an entrant page and an anchor inside an anchor is not a thing HTML has.
    It is not an exception any more: the row is a container, the name carries
    the link, and the chips are links of their own. `index.html` is in this
    list to keep it that way.
    """
    render_site(pool, game_data, tmp_path)

    for name in (
        "index.html",
        "entrant/brandon/index.html",
        "teams/index.html",
        "schedule/index.html",
        "season/index.html",
        "rules/index.html",
        "team/KC/index.html",
    ):
        html = (tmp_path / name).read_text()
        assert re.search(r'<a class="team-chip[^>]*href="/team/\w+/"', html), name


def test_no_page_ever_nests_one_link_inside_another(pool, game_data, tmp_path):
    """Which is what making chips and names clickable could most easily break.

    An anchor inside an anchor is invalid, and browsers recover from it by
    closing the outer one early — so the rest of the row silently stops being
    a link and nobody notices until somebody taps it.
    """
    render_site(pool, game_data, tmp_path)

    for page in tmp_path.rglob("*.html"):
        depth = 0
        for token in re.findall(r"<a\b|</a>", page.read_text()):
            depth += 1 if token == "<a" else -1
            assert depth in (0, 1), f"{page.name}: nested anchor"


# Places that name somebody and are not, and cannot be, a link: an entity's own
# name at the top of its own page, a form control you pick yourself from, a
# caption or heading that explains a table rather than pointing at a person,
# prose about the page's own subject, and an SVG <title>, which is the tooltip
# on a line whose label is already a link. Everything else that names an
# entrant has to be a link.
#
# Kept deliberately narrow. An earlier draft excused every `<p class=…>` and
# quietly excused the leader tile, the week's best and the movers — the three
# things this test was written to hold. A rule here has to name the thing it
# is letting off.
_NOT_A_LINK = (
    r"<title>.*?</title>",
    r"<h[123][^>]*>.*?</h[123]>",
    r"<caption>.*?</caption>",
    r"<option[^>]*>.*?</option>",
    r"<button[^>]*>.*?</button>",
    r'<p class="page-sub">.*?</p>',
    r'<span class="tie-slot">.*?</span>',
)


def _loose_names(html: str, names: Sequence[str]) -> list[str]:
    """Names left visible on a page once every link and every excuse is gone.

    Attributes go first and wholesale. A name in one is never text a reader
    sees — it is a sort key, a description for a screen reader, or the label a
    chart hands its own tooltip — and leaving them in would make this test
    unfalsifiable in the other direction, flagging `data-value="Aunt Carol"` on
    a cell whose only content is a link to Aunt Carol.
    """
    stripped = re.sub(r"<a\b.*?</a>", " ", html, flags=re.S)
    stripped = re.sub(r"<!--.*?-->", " ", stripped, flags=re.S)
    for pattern in _NOT_A_LINK:
        stripped = re.sub(pattern, " ", stripped, flags=re.S)
    return [n for n in names if n in re.sub(r'="[^"]*"', "", stripped)]


def test_a_name_is_a_link_wherever_the_page_says_it(pool, mid_season, tmp_path):
    """The whole point, asserted structurally rather than page by page.

    Every place this site prints somebody's name it is naming the same object,
    and that object has a page. The exceptions are real but small — your own
    name on your own page, the picker you choose yourself from, prose about the
    field rather than about a person — and they are listed above rather than
    left to be rediscovered. Anything outside them is a name that has become a
    dead end, which is exactly the drift this test exists to catch.
    """
    render_site(pool, mid_season, tmp_path, simulations=200)
    names = [e.name for e in pool.entrants]

    pages = [
        (tmp_path / p, names)
        for p in (
            "index.html",
            "season/index.html",
            "forecast/index.html",
            "schedule/index.html",
            "teams/index.html",
            "team/KC/index.html",
        )
    ]
    # An entrant's own page is the one place a name is allowed to be plain —
    # it is the page you are already on — so theirs comes out of the list and
    # everybody else's stays in it.
    pages += [
        (tmp_path / "entrant" / e.slug / "index.html",
         [n for n in names if n != e.name])
        for e in pool.entrants
    ]

    for page, expected in pages:
        loose = _loose_names(page.read_text(), expected)
        assert not loose, f"{page.parent.name}/{page.name}: {loose} named but not linked"


def test_the_board_row_stacks_its_three_layers_in_the_right_order():
    """The one part of this that neither test suite can otherwise see.

    A board row is a container with a link stretched over it and four chips
    lifted back over that, and the whole thing is held up by three z-indexes in
    the stylesheet. Get them wrong and nothing fails: the markup is still
    valid, every href is still correct, and a chip or the score silently stops
    being tappable in a browser. Found exactly that way — the score carries a
    `view-transition-name`, which makes it a stacking context that paints over
    an overlay sitting at zero.
    """
    css = (ASSET_DIR / "site.css").read_text()

    def z(selector: str) -> int:
        start = css.index(selector)
        block = css[start : css.index("}", start)]
        found = re.search(r"z-index:\s*(\d+)", block)
        assert found, f"{selector} has no z-index"
        return int(found.group(1))

    overlay = z(".row-link::after {")
    chips = z(".row-teams {")
    sheen = z(".row::after {")

    assert overlay >= 1, "an overlay at zero loses to the score's own stacking context"
    assert chips > overlay, "chips under the overlay are links nobody can reach"
    assert sheen > chips, "the floodlight has to pass over the chips, not behind them"


def test_a_link_drawn_inside_a_chart_still_carries_the_deployment_prefix(
    pool, mid_season, tmp_path
):
    """The one failure that only ever shows up in production, now in SVG too.

    Chart markup is built in Python, where the `url` filter is not in scope, so
    a chart is the easiest place on the site to hand-build a URL that works
    perfectly on a local preview and 404s once it is deployed under
    /football-pool/. `render_site` passes the environment's own resolver in
    for exactly this reason; this is what says so.
    """
    render_site(pool, mid_season, tmp_path, base="/football-pool", simulations=200)

    found = 0
    for page in tmp_path.rglob("*.html"):
        for chart in re.findall(r"<svg\b.*?</svg>", page.read_text(), re.S):
            for href in re.findall(r'<a href="([^"]*)"', chart):
                assert href.startswith("/football-pool/"), f"{page.name}: {href}"
                found += 1
    # A chart with no links at all would pass the loop above vacuously.
    assert found, "no chart drew a link"


def test_a_chart_that_carries_links_is_not_sealed_off_from_a_screen_reader(
    pool, mid_season, tmp_path
):
    """`role="img"` makes a subtree opaque, links and all.

    Which is right for a picture and wrong the moment the picture contains
    somewhere to go — so a chart that gained links has to have given up that
    role, or it has handed a screen reader a chart with nothing in it.
    """
    render_site(pool, mid_season, tmp_path, simulations=200)

    for page in tmp_path.rglob("*.html"):
        for chart in re.findall(r"<svg\b[^>]*>.*?</svg>", page.read_text(), re.S):
            if "<a href=" not in chart:
                continue
            assert 'role="img"' not in chart, page.name
            assert 'role="group"' in chart, page.name


def test_an_entrant_page_shows_their_own_odds(pool, mid_season, tmp_path):
    render_site(pool, mid_season, tmp_path, simulations=200)
    html = (tmp_path / "entrant" / "brandon" / "index.html").read_text()

    assert 'class="finish"' in html
    assert "Favoured against" in html
    # Every rival but themselves.
    assert html.count("<tbody>") >= 1
    for other in ("Aunt Carol", "Cousin Mike"):
        assert other in html


def test_short_names_fall_back_when_first_names_collide():
    """Two Sarahs must not both become "Sarah" on a chart axis."""
    from football_pool.render import _short_names

    assert _short_names(["Brian Moore", "Paul Moore"]) == {
        "Brian Moore": "Brian",
        "Paul Moore": "Paul",
    }
    clash = _short_names(["Sarah Jones", "Sarah Smith"])
    assert clash == {"Sarah Jones": "Sarah Jones", "Sarah Smith": "Sarah Smith"}


def test_the_data_feed_carries_data_not_markup(pool, mid_season, tmp_path):
    """standings.json is a machine-readable interface, so no SVG in it.

    Every chart is a string of markup. One leaking into the feed tripled its
    size, and anyone parsing it wants the numbers.
    """
    render_site(pool, mid_season, tmp_path, simulations=200)
    raw = (tmp_path / "data" / "standings.json").read_text()

    assert "<svg" not in raw
    data = json.loads(raw)
    projection = data["entrants"][0]["projection"]
    # The numbers behind the charts are still there.
    assert {"p_first", "p_cash", "mean_points", "rivals"} <= set(projection)


# -- the schedule -------------------------------------------------------------
def test_the_schedule_has_a_section_for_every_week(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    # A complete season: 18 regular weeks plus the four playoff rounds.
    ids = re.findall(r'<section class="week[^"]*"\s+id="week-(\d+)"', html)
    assert [int(i) for i in ids] == list(range(1, 23))


def test_the_schedule_lists_every_game_exactly_once(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    listed = re.findall(r'data-game="([^"]+)"', html)
    assert sorted(listed) == sorted(game_data.games["game_id"])


def test_exactly_one_week_opens_by_default(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert html.count("is-default") == 1


def test_the_default_week_follows_the_data_clock(pool, games_2025, tmp_path):
    """The core of the feature: which week opens depends on when you look.

    Two builds of identical games, differing only in when the data was fetched,
    must open on different weeks. Derived from ``fetched_at`` rather than
    ``now()`` so a rebuild of unchanged data stays byte-identical.
    """

    def default_week_at(when, out):
        render_site(pool, GameData(games_2025, 2025, when, None, "cache"), out)
        html = (out / "schedule" / "index.html").read_text()
        return re.search(r'<section class="week is-default"\s+id="week-(\d+)"', html).group(1)

    september = datetime(2025, 9, 18, 12, 0, tzinfo=timezone.utc)
    november = datetime(2025, 11, 20, 12, 0, tzinfo=timezone.utc)

    early = default_week_at(september, tmp_path / "a")
    late = default_week_at(november, tmp_path / "b")
    assert int(early) < int(late)


def test_the_preseason_schedule_opens_on_week_one(pool, games_2025, tmp_path):
    g = games_2025.copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    before = datetime(2025, 8, 1, 12, 0, tzinfo=timezone.utc)
    render_site(pool, GameData(g, 2025, before, None, "cache"), tmp_path)

    html = (tmp_path / "schedule" / "index.html").read_text()
    assert re.search(r'class="week is-default"\s+id="week-1"', html)


def test_every_kickoff_carries_a_machine_readable_instant(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    stamps = re.findall(r'<time datetime="([^"]+)" data-ts="kickoff">', html)
    # One per game, plus one per week header.
    assert len(stamps) == len(game_data.games) + 22
    for iso in stamps:
        assert datetime.fromisoformat(iso).tzinfo is not None


def test_a_kickoff_reads_as_a_time_before_any_javascript_runs(pool, game_data, tmp_path):
    """No-JS visitors get Eastern words, not an ISO string."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    texts = re.findall(r'data-ts="kickoff">([^<]+)</time>', html)
    assert texts, "no kickoff stamps rendered"
    assert all(re.match(r"^[A-Z][a-z]{2}, [A-Z][a-z]{2} \d+, \d+:\d\d [AP]M E[SD]T$", t) for t in texts)


def test_changing_week_needs_no_javascript(pool, game_data, tmp_path):
    """Every week is a plain anchor to a real id, and none of them is `hidden`.

    Which week shows is decided by `:target` in CSS. The script only ever moves
    the default when the visitor's clock disagrees with the build's, so the page
    is fully usable with scripting off.
    """
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    ids = set(re.findall(r'<section class="week[^"]*"\s+id="(week-\d+)"', html))
    links = set(re.findall(r'<a href="(#week-\d+)"', html))
    assert links == {f"#{i}" for i in ids}
    assert "<section class=\"week\" hidden" not in html
    assert not re.search(r'<section class="week[^"]*"[^>]*\bhidden\b', html)


def test_the_schedule_prices_both_sides_of_a_game(pool, games_2025, tmp_path):
    """The point of the page: a win pays the *winner's* leveling factor.

    Two teams with different factors meeting must therefore show two different
    numbers, which no generic schedule would.
    """
    g = games_2025.copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    render_site(pool, GameData(g, 2025, datetime(2025, 8, 1, tzinfo=timezone.utc), None, "cache"), tmp_path)

    # The weeks only — see above; the bracket prices January separately.
    html = (tmp_path / "schedule" / "index.html").read_text().split('id="bracket"')[0]
    stakes = re.findall(r'<span class="stake">([\d.]+)</span>', html)
    assert len(stakes) == 2 * len(g)
    assert len(set(stakes)) > 1


def test_the_schedule_dims_games_nobody_in_the_pool_owns(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    # Twelve teams out of thirty-two are held, so a good share of the slate has
    # no pool interest at all — and it should recede rather than compete.
    idle = html.count("is-idle")
    assert 0 < idle < len(game_data.games)


def test_a_played_game_shows_its_score_and_who_won(pool, game_data, tmp_path):
    render_site(pool, game_data, tmp_path)
    # The weeks only: the bracket is on the same page and scores its own games
    # again, which is the point of it and not a second copy of this assertion.
    html = (tmp_path / "schedule" / "index.html").read_text().split('id="bracket"')[0]

    assert html.count('class="game-score"') == 2 * len(game_data.games)
    assert "game-side away won" in html or "game-side home won" in html
    assert "game-side away lost" in html or "game-side home lost" in html
    # Every game is final, so nothing should still be advertising a price.
    assert 'class="stake"' not in html


def test_the_schedule_offers_every_entrant_their_own_stake(pool, game_data, tmp_path):
    """`initMe` reveals one of these per row; the rest stay in the markup."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    for slug in ("aunt-carol", "cousin-mike", "brandon"):
        assert f'<span class="mine" data-slug="{slug}">' in html


def test_the_schedule_tab_is_in_the_nav_on_every_page(pool, game_data, tmp_path):
    written = render_site(pool, game_data, tmp_path)
    for page, text in _real_pages(written):
        assert 'href="/schedule/"' in text, page


def test_the_season_tab_replaces_the_two_it_merged(pool, game_data, tmp_path):
    """Weeks and Trends told one story between them; Season tells it in one tab."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "index.html").read_text()

    assert ">Season</a>" in html
    assert 'href="/season/"' in html
    # The old addresses still resolve — test_weeks_and_trends_forward_to_season
    # covers that — but nothing on the site should route a reader through a stub.
    assert 'href="/weeks/"' not in html
    assert 'href="/trends/"' not in html


def test_the_schedule_shows_no_model_numbers_when_the_model_is_off(
    make_season, games_2025, tmp_path
):
    pool = make_season(
        [{"name": "Solo", "teams": ["KC", "SEA", "DAL", "NE"]}], year=2025, forecast=False
    )
    g = games_2025.copy()
    g[["played", "home_won", "away_won", "is_tie"]] = False
    render_site(pool, GameData(g, 2025, datetime(2025, 8, 1, tzinfo=timezone.utc), None, "cache"), tmp_path)

    html = (tmp_path / "schedule" / "index.html").read_text()
    assert 'class="p-win model"' not in html
    # The factual half of the page is unaffected — that is the whole point of
    # keeping the two tiers separate.
    assert 'class="stake"' in html


# -- byes -------------------------------------------------------------------
def test_the_schedule_names_who_is_on_a_bye(pool, game_data, tmp_path):
    """A bye has no game to render, so subtracting is the only way to show it."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert "On bye" in html
    assert "team-chip bye" in html


def test_a_bye_carries_whoever_holds_the_team(pool, games_2025):
    ctx = build_context(pool, GameData(games_2025, 2025, NOW, None, "cache"))
    weeks = _schedule(ctx)["weeks"]

    owned = [b for w in weeks for b in w["byes"] if b["owners"]]
    assert owned, "somebody in the pool must have a team on a bye at some point"
    # Owners first, so an entrant scanning a week sees their own team is off.
    for week in weeks:
        flags = [bool(b["owners"]) for b in week["byes"]]
        assert flags == sorted(flags, reverse=True)


def test_the_playoffs_have_no_byes_worth_naming(pool, games_2025):
    """In January "not playing" is two dozen eliminated teams, not a bye."""
    ctx = build_context(pool, GameData(games_2025, 2025, NOW, None, "cache"))
    for week in _schedule(ctx)["weeks"]:
        if not week["label"].startswith("Week"):
            assert week["byes"] == []


def test_every_team_gets_exactly_one_bye_across_a_real_season(pool, games_2025):
    """The invariant that makes this the right way to compute a bye at all.

    Byes are derived by subtraction — everyone in the league not playing this
    week — so if the arithmetic is right, adding the regular season up returns
    each of the 32 teams once and only once.
    """
    ctx = build_context(pool, GameData(games_2025, 2025, NOW, None, "cache"))
    weeks = [w for w in _schedule(ctx)["weeks"] if w["label"].startswith("Week")]

    off = Counter(b["team"] for w in weeks for b in w["byes"])
    assert set(off) == set(pool.teams)
    assert set(off.values()) == {1}
    # And week 1 is the week nobody is off, every year.
    assert weeks[0]["byes"] == []


def test_an_entrant_is_told_which_of_their_teams_is_off_next_week(pool, games_2025):
    """Half a season in, so there is a next week and byes are still running."""
    part = games_2025.copy()
    part.loc[part["week"] > 7, ["played", "home_won", "away_won", "is_tie"]] = False
    ctx = build_context(pool, GameData(part, 2025, NOW, None, "cache"))
    rows = _entrant_rows(ctx)

    assert all(r["bye_week"] == 8 for r in rows)
    # Only ever their own teams, never the rest of the league.
    for row in rows:
        assert set(row["byes"]) <= set(row["teams"])


def test_a_finished_season_has_no_next_week_to_report(pool, game_data):
    ctx = build_context(pool, game_data)
    rows = _entrant_rows(ctx)
    assert all(r["bye_week"] is None and r["byes"] == [] for r in rows)


# -- the forecast says which question it is answering ------------------------
def test_the_forecast_separates_winning_from_making_money(pool, mid_season, tmp_path):
    """Two questions with two answers, both named rather than left to guess."""
    render_site(pool, mid_season, tmp_path)
    html = (tmp_path / "forecast" / "index.html").read_text()

    assert "Chance of winning" in html
    assert "Expected payout" in html
    assert "Expected profit" in html
    # And the old ambiguous headings are gone.
    assert "P(1st)" not in html
    assert "Expected $" not in html


def test_the_forecast_names_a_leader_for_each_question(pool, mid_season):
    ctx = build_context(pool, mid_season)
    forecast = _forecast(ctx)

    for headline in (forecast["best_odds"], forecast["best_money"]):
        assert headline["name"]
        assert headline["slug"]
        assert 0.0 <= headline["p_first"] <= 1.0
        assert headline["expected_payout"] >= 0.0

    # Each is genuinely the best on its own column, which is the whole claim.
    entrants = ctx.projections.entrants
    assert forecast["best_odds"]["p_first"] == pytest.approx(entrants["p_first"].max())
    assert forecast["best_money"]["expected_payout"] == pytest.approx(
        entrants["expected_payout"].max()
    )


# -- table ordering ----------------------------------------------------------
def test_the_teams_table_falls_back_to_leveling_factor_before_any_games(pool, games_2025):
    """Every team has scored zero in August, and zero is not an order."""
    empty = games_2025.copy()
    empty[["played", "home_won", "away_won", "is_tie"]] = False
    ctx = build_context(pool, GameData(empty, 2025, NOW, None, "cache"))
    rows = _team_rows(ctx)

    assert all(r["points"] == 0 for r in rows)
    lfs = [r["lf"] for r in rows]
    assert lfs == sorted(lfs, reverse=True)


def test_the_teams_table_leads_with_points_once_there_are_any(pool, games_2025):
    ctx = build_context(pool, GameData(games_2025, 2025, NOW, None, "cache"))
    points = [r["points"] for r in _team_rows(ctx)]
    assert points == sorted(points, reverse=True)


def test_the_teams_table_order_is_stable_across_rebuilds(pool, games_2025):
    """A rebuild of unchanged data must produce an unchanged page."""
    empty = games_2025.copy()
    empty[["played", "home_won", "away_won", "is_tie"]] = False
    data = GameData(empty, 2025, NOW, None, "cache")
    first = [r["team"] for r in _team_rows(build_context(pool, data))]
    second = [r["team"] for r in _team_rows(build_context(pool, data))]
    assert first == second


def test_a_sorted_table_says_so_in_aria_sort(pool, game_data, tmp_path):
    """The heading has to agree with the rows underneath it.

    Otherwise the first click on that column "sorts" it to the order it is
    already in, and looks broken.
    """
    render_site(pool, game_data, tmp_path)

    for page in ("season/index.html", "teams/index.html"):
        html = (tmp_path / page).read_text()
        assert 'aria-sort=' in html


def test_rank_columns_open_first_place_first(pool, game_data, tmp_path):
    """The one kind of number where biggest-first is exactly wrong."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "season" / "index.html").read_text()
    assert 'data-sort="ascending"' in html


# -- definitions on the page -------------------------------------------------
def test_the_jargon_carries_its_definition_where_it_is_used(pool, game_data, tmp_path):
    """An info button next to a word, with the whole definition behind it."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()

    assert 'class="info"' in html
    assert 'class="def"' in html
    # The definition itself, not merely a reference to one.
    assert "The most the whole pool could bank in this week" in html


def test_the_definition_is_the_button_s_accessible_name(pool, game_data, tmp_path):
    """So a screen reader reads it outright and has nothing to open.

    The popover is placed by the client; the accessible name is not, which
    makes it the version that always works.
    """
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "schedule" / "index.html").read_text()
    assert re.search(r'class="visually-hidden">On the table: ', html)


def test_no_definition_button_sits_inside_a_link(pool, game_data, tmp_path):
    """A button inside an anchor is invalid, and taps land on the wrong one.

    The leaderboard rows and the forecast rows are both whole-row links, so
    this is a real trap rather than a theoretical one.
    """
    render_site(pool, game_data, tmp_path)

    for page in tmp_path.rglob("*.html"):
        html = page.read_text()
        for link in re.findall(r"<a\b[^>]*>(.*?)</a>", html, re.S):
            assert 'class="info"' not in link, page.name


def test_the_rules_page_carries_the_whole_glossary(pool, game_data, tmp_path):
    """Where the definitions still are when the popovers cannot open."""
    render_site(pool, game_data, tmp_path)
    html = (tmp_path / "rules" / "index.html").read_text()

    assert "What the words mean" in html
    for term in ("Leveling factor", "On the table", "Expected payout", "Bye"):
        assert term in html


# -- more than one pool on one site -------------------------------------------
def test_a_page_url_is_pool_relative_and_an_asset_url_is_not():
    """The composite case: a deployment prefix AND a pool below the root.

    Each axis on its own is covered above. This is the combination where a bug
    hides — a pool-scoped asset URL 404s only on the non-root pool, only in
    production, and a site-scoped page URL sends the friends pool's nav to the
    family pool's board.
    """
    env = make_environment("/football-pool", pool_base="/football-pool/friends")
    url = env.filters["url"]

    assert url("/rules/") == "/football-pool/friends/rules/"
    assert url("/") == "/football-pool/friends/"
    assert url("/data/standings.json") == "/football-pool/friends/data/standings.json"
    assert url("/assets/site.css").startswith("/football-pool/assets/site.css?v=")
    assert "/friends/assets/" not in url("/assets/site.css")


def test_omitting_pool_base_leaves_the_filter_exactly_as_it_was():
    """The one-pool call shape must not have changed behaviour."""
    both = make_environment("/football-pool").filters["url"]
    explicit = make_environment("/football-pool", pool_base="/football-pool").filters["url"]
    for path in ("/", "/rules/", "/assets/site.css", "#scoring", "https://x.test/"):
        assert both(path) == explicit(path)


def test_render_pools_puts_the_root_pool_at_the_root(two_pools, game_data, tmp_path):
    render_pools(two_pools, game_data, tmp_path, simulations=SIMS)

    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "friends" / "index.html").exists()
    # Not at /family/ — the root pool has no segment at all.
    assert not (tmp_path / "family").exists()


def test_the_assets_are_copied_once_for_the_whole_site(two_pools, game_data, tmp_path):
    render_pools(two_pools, game_data, tmp_path, simulations=SIMS)

    assert (tmp_path / "assets" / "site.css").exists()
    assert not (tmp_path / "friends" / "assets").exists()


def test_no_root_absolute_url_escapes_the_prefix_on_a_nested_pool(
    two_pools, game_data, tmp_path
):
    """The root-pool version of this exists above; the nested pool is where a
    bad prefix actually hides."""
    render_pools(two_pools, game_data, tmp_path, base="/football-pool", simulations=SIMS)

    for page in (tmp_path / "friends").rglob("*.html"):
        for match in re.findall(r'(?:href|src)="(/[^"]*)"', page.read_text()):
            assert match.startswith("/football-pool/"), f"{page.name}: {match}"


def test_each_pool_keeps_its_own_money_and_field(two_pools, game_data, tmp_path):
    render_pools(two_pools, game_data, tmp_path, simulations=SIMS)

    family = json.loads((tmp_path / "data" / "standings.json").read_text())
    friends = json.loads((tmp_path / "friends" / "data" / "standings.json").read_text())

    assert family["pool"] == {
        "slug": "family", "name": "Family Pool", "path": "",
        "entry_fee": 10.0, "pot": 30.0,
    }
    assert friends["pool"] == {
        "slug": "friends", "name": "Friends Pool", "path": "friends",
        "entry_fee": 50.0, "pot": 100.0,
    }
    assert len(family["entrants"]) == 3
    assert len(friends["entrants"]) == 2
    # Nobody leaks across: the two rosters share no names.
    assert not {e["name"] for e in family["entrants"]} & {
        e["name"] for e in friends["entrants"]
    }


def test_no_pool_ever_links_to_another_pool(two_pools, game_data, tmp_path):
    """The pools share a domain, not an experience.

    Each group gets exactly one URL. A visitor to the family pool must never
    see a link to the friends pool (or vice versa) — someone who follows one
    lands on a roster that has no idea who they are, and rightly wonders where
    their name went. Every page of both builds is checked, because a stray link
    in a footer is exactly as confusing as one in the masthead.
    """
    render_pools(two_pools, game_data, tmp_path, base="/football-pool", simulations=SIMS)

    friends_dir = tmp_path / "friends"
    for page in tmp_path.rglob("*.html"):
        html = page.read_text()
        if friends_dir in page.parents:
            # Inside the friends pool, no URL reaches back up to the root pool.
            assert 'href="/football-pool/"' not in html, page
            assert "Family Pool" not in html, page
        else:
            # And the root pool never names or links the nested one.
            assert 'href="/football-pool/friends/' not in html, page
            assert "Friends Pool" not in html, page


def test_every_page_of_a_nested_pool_carries_its_own_prefix(
    two_pools, game_data, tmp_path
):
    """Not just the front page — the nav on every page has to stay in the pool."""
    render_pools(two_pools, game_data, tmp_path, base="/football-pool", simulations=SIMS)

    for name in ("index.html", "rules/index.html", "season/index.html"):
        html = (tmp_path / "friends" / name).read_text()
        assert 'href="/football-pool/friends/rules/"' in html
        assert 'href="/football-pool/friends/schedule/"' in html


def test_each_pool_scopes_its_identity_storage(two_pools, game_data, tmp_path):
    """data-pool is what site.js reads to namespace `pool-me`."""
    render_pools(two_pools, game_data, tmp_path, simulations=SIMS)

    assert 'data-pool=""' in (tmp_path / "index.html").read_text()
    assert 'data-pool="friends"' in (tmp_path / "friends" / "index.html").read_text()
