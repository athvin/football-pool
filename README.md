# Family NFL Pool 🏈

A static scoreboard for our family's leveling-factor pool. A GitHub Action
refreshes it twice a day, recomputes everyone's totals from real NFL results,
and publishes the site to GitHub Pages.

## How the pool works

Everyone picks 4 teams for the season. Every team carries a **leveling factor**
— a handicap set from last year's record — and each win pays that team's LF, so
a win by a bad team is worth more than a win by a good one.

| Event | Points |
|---|---|
| Regular-season win | + the team's LF |
| Regular-season tie | + 0.5 × LF |
| Division winner | +3.0 |
| Wild-card berth | +1.5 |
| Wild-card round win | +1.0 flat — **only** when a wild card beats a division winner |
| Divisional round win | +1.0 + LF |
| Conference championship win | +1.5 + LF |
| Super Bowl win | +2.0 + LF |

The `/rules/` page on the site renders from the same file the scoring engine
reads, so the posted rules and the maths can never drift apart.

## Getting started

```bash
uv sync                       # install
uv run pool standings         # print the leaderboard
uv run pool build             # generate the site into public/
uv run pytest                 # Python tests
npm ci && npx vitest run      # JavaScript tests
```

To preview the site locally:

```bash
uv run pool build && (cd public && python3 -m http.server 8000)
```

Build locally with no `--base`, because a local server serves from the root. CI
passes the real deployment prefix. Getting this wrong produces a site that works
perfectly on your laptop and 404s every stylesheet in production.

## Adding people

Edit `seasons/2026/picks.yaml`:

```yaml
entrants:
  - name: Brandon
    teams: ["CIN", "WAS", "TEN", "NO"]
  - name: Aunt Carol
    teams: ["SEA", "NE", "PHI", "LAR"]
```

The build validates this hard and fails loudly on a typo — exactly 4 teams, all
real codes, no duplicates within an entry. A misspelled `KAN` for `KC` would
otherwise silently score somebody zero for a team all season.

Quote the team codes. YAML reads a bare `NO` as the boolean `false`, which would
quietly erase New Orleans from the pool.

The pot, the payouts, and every pool-relative number follow the number of
entrants in this file, so you can add people as their picks arrive.

## Where the leveling factors come from

The commissioner sets them, and this project never overrides that. But the
structure is recoverable, which makes a new year quick and a typo catchable:

- Each conference is ranked by prior-season wins, a tie counting as half a win.
- The factor rises monotonically down that ranking.
- Clubs on identical records share an identical factor.

That reproduces **31 of the 32** 2026 values exactly from 2025 records. The one
exception is New England (1.10) and Denver (1.20), both 14–3 — New England
reached the Super Bowl and Denver did not, so the tie appears to have been
broken on how far each went in January.

The gist's `lf_linear` (`3.05 - 0.136 × wins`) describes that curve well
(R² > .95) but reproduces **none** of the 32 values exactly, so it summarises
the shape rather than generating the numbers.

```bash
uv run pool check-lf              # compare rules.yaml against last season
uv run pool check-lf --prior 2025 # pick the season to compare against
```

It prints both conferences ranked, the configured factor beside what the
structure would propose, and flags anything that goes the wrong way down the
standings. A deliberate tiebreak shows up as a flag too — the tool reports, it
does not decide.

`tests/test_official_rules.py` pins all of this. Values from the commissioner's
published sheet are asserted exactly; every season directory is additionally
checked for monotonicity and tie-consistency against the prior year, so adding
`seasons/2027/` enrols it automatically with no test edit.

## Rolling over to a new season

```bash
cp -r seasons/2026 seasons/2027
# edit rules.yaml (leveling factors), picks.yaml, forecast.yaml
# set active_season: 2027 in config.yaml
```

Nothing season-specific lives in code. Past years stay buildable forever with
`uv run pool build --season 2026`.

## Layout

```
config.yaml           which season to build
seasons/<year>/       rules, picks, and forecast inputs for that year
data/<year>/          committed results — an audit trail and offline fallback
src/football_pool/
  season.py           loads a season's config into a frozen Season object
  nflverse.py         fetches and normalises NFL results
  scoring.py          the scoring engine — pure functions, exhaustively tested
  standings.py        NFL tiebreakers → division winners and playoff seeds
  potential.py        next week, ceilings, floors, elimination
  history.py          week-by-week points and ranks
  svg.py              inline charts, generated at build time
  render.py           Jinja2 → public/
templates/, assets/   the site itself
```

## Notes on the data

Results come from one file:
`nflverse-data/releases/download/schedules/games.csv`. Upstream commits every
15–90 minutes year round and lands within minutes of a game going final, so the
morning rebuild always has the previous night's scores.

If the fetch fails, the build falls back to the committed copy in `data/` — an
outage degrades the site to yesterday's numbers rather than breaking it. The
footer shows two timestamps for that reason: when the **data** was published and
when the **site** was built, because a fresh build of stale data is still stale.

Standings and playoff seeds are derived here rather than read, because nflverse
publishes neither. The tiebreaker implementation reproduces all 70 playoff seeds
for 2021–2025 exactly against ESPN's published seeding, and the test suite
checks that on every run.

## Projections

The site also forecasts. On every build it fits team ratings to the market's
win totals, then plays the rest of the season 25,000 times — **freezing every
game that already has a final score** — and scores the real field against the
results. That produces each entrant's chance of winning, chance of cashing,
expected payout in dollars, and a p10–p90 band for their final score.

This is what makes the site worth opening in August, when every actual total is
still 0.00.

Two deliberate limits:

- **Projections stop when the regular season does.** Once the bracket starts,
  simulating it would mean re-playing games that already happened, so the panels
  disappear rather than show numbers that can't be defended. By then the banked
  totals and elimination maths tell the story anyway.
- **A modelling failure never takes the site down.** If the projection layer
  raises, the build warns and carries on; actual standings are the point.

Everything modelled is rendered in cyan and labelled *modelled*, so a forecast
is never mistaken for something that already happened. The inputs live in
`seasons/<year>/forecast.yaml` — set `enabled: false` to turn the whole layer
off, and nothing else changes.

## The pages

- **Standings** — the leaderboard, with the banked/guaranteed/ceiling bar, plus
  the projection table.
- **Weeks** — points scored in each week and the standings as they stood after it.
- **Trends** — points and rank over the season, leverage, who is carrying whom,
  and the gaps between neighbours.
- **Teams** — every team's leveling factor, record, points generated, and owners.
- **Rules** — rendered from `rules.yaml`, the same file the engine reads.

The Trends page carries two kinds of chart, because they answer two different
questions.

**Compare** is the one you will use. Pick up to six people and their lines come
forward, each in its own colour, assigned in the order you pick them so nobody
changes hue as the season moves. Set *who are you?* in the footer and the chart
opens on your own line every time — that choice also highlights your row on
every other page. It is stored in your browser and goes nowhere else.

**The whole field** draws everyone in a single colour with only the top few
labelled. Thirty distinguishable hues do not exist, and colouring by rank would
make people change colour week to week, so the chart would contradict itself as
the season moved. Hovering any line brings it forward.

Both are rendered as inline SVG at build time; picking only toggles classes, so
with JavaScript off the charts still show the full field.

The site is dark by default and does not follow your operating system — light is
an opt-in from the toggle in the header, remembered per browser.

## Two things the numbers account for

**Your own teams play each other.** Almost every 4-team entry has games where
two of its own picks meet. One of them has to win, so those points are banked
before kickoff — that is the hatched segment on the standings bar, and it is why
nobody's floor is simply what they have scored so far.

**Playoff structure binds the ceiling.** A team earns the division bonus or the
wild-card bonus, never both; two of your teams in one division cannot both win
it; only one team in the league wins the Super Bowl. The ceiling is computed
against those constraints, which is what makes the "mathematically eliminated"
badge trustworthy.

## Changing anything

`main` is protected by a repository ruleset, so changes land through a pull
request:

```bash
git checkout -b bm/whatever
# ... work ...
git push -u origin bm/whatever
gh pr create --fill
```

`.github/workflows/ci.yml` then runs three required checks — **python**,
**javascript** and **build** — and the merge button stays disabled until all
three are green. The build check renders the site twice, once at `/` and once at
`/football-pool/`, because a root-absolute asset URL works perfectly on a local
preview and 404s only in production.

The ruleset also blocks force-pushes and deletion of `main`. The repository
admin can bypass it, which is deliberate: with one maintainer, a ruleset nobody
can override is a lockout waiting to happen the first time CI itself breaks.
To make the gate absolute, remove the bypass:

```bash
gh api /repos/athvin/football-pool/rulesets            # find the id
gh api --method PUT /repos/athvin/football-pool/rulesets/<id> \
  -f 'bypass_actors=[]'
```

### The one wrinkle

Requiring pull requests means the daily job can no longer push its data
snapshot: `github-actions[bot]` does not hold the admin role, and a user-owned
repository cannot grant a ruleset bypass to the Actions app — that option is
organisation-only. The push is therefore best-effort and logs a warning instead
of failing the run; **the site still builds and deploys from freshly fetched
data every time**, since nothing on the page comes from the committed snapshot.

Adding a fine-grained PAT with contents:write as the `DATA_PUSH_TOKEN` secret
restores it, and is worth doing anyway — it inherits your admin bypass *and*
counts as real repository activity against the 60-day timer below, which the
default token does not.

## Deploying

One-time setup: **Settings → Pages → Source: GitHub Actions.**

After that `.github/workflows/daily.yml` runs at 07:37 and 19:37 Eastern, plus
on demand from the Actions tab. Both test suites gate the deploy — if a scoring
test breaks, the site is not republished and yesterday's good version stays up.

Scheduled workflows are disabled after 60 days of repository inactivity and the
offseason is longer than that, so the job commits its data snapshot partly to
keep the repo active. GitHub emails a warning first, and re-enabling is one
click.
