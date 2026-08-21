# NFL Pool 🏈

A static scoreboard for our leveling-factor pools. A GitHub Action refreshes it
twice a day, recomputes everyone's totals from real NFL results, and publishes
the site to GitHub Pages.

One season can carry more than one pool — different people, different stakes,
the same football. Today there are two:

| | | |
|---|---|---|
| **Family Pool** | $10 | [athvin.github.io/football-pool/](https://athvin.github.io/football-pool/) |
| **Friends Pool** | $50 | [athvin.github.io/football-pool/friends/](https://athvin.github.io/football-pool/friends/) |

The two share a domain as an implementation detail, not an experience: **no
page in one pool links to the other**, and neither ever names the other. Each
group gets exactly one URL. The alternative — a switcher in the header — was
tried and removed: a family member who taps "Friends Pool", doesn't find their
own name, and doesn't know there are two pools, concludes the site is broken,
and every one of those conclusions becomes a text to the commissioner.

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

## More than one pool

A **season** owns the football; a **pool** owns the people and the money.

| Season-level, shared by every pool | Per-pool |
|---|---|
| `rules.yaml` — leveling factors, bonuses, divisions | `name` |
| `forecast.yaml` — simulation inputs | `entry_fee`, `payout_split` |
| `data/<year>/games.csv` — the results | `picks_per_entrant` |
| | `entrants` |

That split is the whole design. There is exactly **one** leveling-factor table
per year, so two pools cannot quietly disagree about what a win is worth, and
nothing a pool declares can reach the maths.

```
seasons/2026/
  rules.yaml          shared scoring
  forecast.yaml       shared model inputs
  pools/
    family.yaml       name, $10, payout split, 11 entrants, root: true
    friends.yaml      name, $50, payout split, entrants
```

**The filename is the slug, and the slug is the URL.** `friends.yaml` is served
at `/friends/`. Exactly one pool sets `root: true` and is served at the site
root instead — that is the family pool, and it stays there, because a year of
group-chat links point at it. Moving it is a one-way door.

There is no manifest listing the pools; the directory *is* the list. A manifest
can disagree with what is on disk in two directions — listed but missing,
present but unpublished — and both failures are quiet.

To add a pool mid-season: write `seasons/2026/pools/<slug>.yaml`. Nothing in
code changes, and the next scheduled build publishes it at `/<slug>/`. Slugs
must be lowercase `[a-z0-9-]` and may not collide with a page the site already
writes (`rules`, `teams`, `entrant`, `assets`, `data`, …) — the loader refuses
those by name, because a pool slugged `teams` would render its board straight
over the teams page.

Each pool gets a complete site of its own: its own leaderboard, entrant pages,
schedule, forecast and `data/standings.json`. The one thing they share on disk
is `/assets/` — a single copy of the stylesheet, the script, the logos and the
fonts, linked by the same URL from every pool. That sharing stops at assets:
no rendered page carries a link to, or the name of, any pool but its own, and
both CI and the test suite grep the built markup to keep it that way.

One build renders all of them:

```bash
uv run pool build                      # every pool in the season
uv run pool build --pool friends       # just one, into its real subpath
uv run pool standings --pool friends   # that pool's leaderboard
```

Two consequences worth knowing up front. The results feed is fetched once and
the staleness guard runs before any rendering, so **stale data blocks every
pool** — that is deliberate; a half-published site is worse than yesterday's
good one. And `/404.html` is only served from the site root, so a visitor who
mistypes a URL under `/friends/` gets a page branded with the root pool's name.

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

Edit the pool's own file — `seasons/2026/pools/family.yaml`:

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

The commissioner sets them, and this project never overrides that. They live in
`rules.yaml` at the season level, so there is one table shared by every pool and
nothing to keep in sync. But the structure is recoverable, which makes a new
year quick and a typo catchable:

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
# edit rules.yaml     leveling factors for the new year
# edit forecast.yaml  win totals, qualitative Elo
# edit pools/*.yaml   the new rosters, and the money if it changed
# set active_season: 2027 in config.yaml
```

Two things `cp -r` will happily carry that you may not want. It copies each
pool file **with last year's roster**, which is the right default — most people
re-enter — but an unedited roster publishes a stale field and validates
perfectly clean, so the picks validator cannot catch it for you. And a pool
that isn't running this year has to be **deleted** from `pools/`, not left in
place; there is no "off" switch, because a pool nobody publishes is a pool
nobody notices is broken.

Nothing season-specific lives in code. Past years stay buildable forever with
`uv run pool build --season 2026`.

## Layout

```
config.yaml           which season to build
seasons/<year>/
  rules.yaml          scoring: leveling factors, bonuses, divisions — shared
  forecast.yaml       simulation inputs — shared
  pools/<slug>.yaml   one pool: its name, its money, its roster
data/<year>/          committed results — an audit trail and offline fallback
src/football_pool/
  season.py           loads a season's config into a frozen Season object
  nflverse.py         fetches and normalises NFL results
  scoring.py          the scoring engine — pure functions, exhaustively tested
  standings.py        NFL tiebreakers → division winners and playoff seeds
  potential.py        next week, ceilings, floors, elimination
  history.py          week-by-week points and ranks
  project.py          Monte Carlo → per-entrant odds and distributions
  glossary.py         what the site's words mean, built from the season's rules
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

That fallback has a floor under it. "Yesterday's numbers" is only acceptable
while the committed copy really is from yesterday, and it stops being true the
moment something prevents it being refreshed — which branch protection does,
since the daily job can no longer push to `main`. Left alone, an unreachable
feed in week 12 would republish an August snapshot and quietly show everyone
`0.00`. A silently wrong leaderboard is worse than a missing one, because it
looks exactly like a right one.

So the build refuses to publish a fallback that is materially behind, and the
deploy job depends on the build, so the previous good site simply stays up until
the next run.

Staleness is one number: **how many days of results the file is missing**,
read on the Eastern clock that `gameday` is written in. Zero when current.

It calibrates itself where a clock cannot — the committed copy can be six months
old in August and still be perfectly correct, because nothing has been played.
The limit is two days, measured rather than guessed: replaying a real season at
both cron times, a current file scores 0 at every build instant, a file up to
thirty hours old scores at most 1, and thirty-six hours is the first to reach 2.
So the degradation this was always meant to allow still happens — an outage
falls back to yesterday's numbers — while anything that has lost a slate is
refused. Two consecutive failed runs is not an ordinary day.

Days rather than games, deliberately. A game count cannot span a sixteen-game
Sunday and a one-game Super Bowl with one threshold, and a threshold set for a
slate keeps publishing a wrong leaderboard for **ten days** after a Sunday
freeze. Days catch the same freeze on the fourth.

Two cases need care, and both are handled by asking what "nothing outstanding"
means. nflverse does not publish postseason rows until the field is set, so a
copy frozen at the end of week 18 has every game it knows about played and reads
as perfectly current — for the whole of January, the window that decides the
money. A truncated copy looks identical, because the rows it loses are the most
recent ones. Absence cannot be counted, so nothing outstanding is only trusted
when the file ran to a played Super Bowl; otherwise the measure becomes how long
we have been in the dark.

The test is the data, never where it came from. A 200 is not the same as good
data — a regenerated release asset or a stale CDN object answers perfectly while
carrying no results — so the same measure also gates the cache write. A
successful but empty response can neither be published nor overwrite the good
committed copy.

An explicit `--offline` build is never blocked. Asking for the committed copy is
a choice, and CI relies on it to build deterministically; falling back to it
because the network failed is a degraded state. The two report as `cache` and
`fallback` so they can never be confused.

Standings and playoff seeds are derived here rather than read, because nflverse
publishes neither. The tiebreaker implementation reproduces all 70 playoff seeds
for 2021–2025 exactly against ESPN's published seeding, and the test suite
checks that on every run.

Mid-season the seed shown is the *projected* field if the standings froze that
day. Before the first kickoff there is no field and the site says so with a
dash: with every club 0-0 the tiebreaker ladder has nothing to work with, runs
out of steps and reaches its coin-toss fallback, which sorts alphabetically to
keep builds reproducible — so a "projection" then would only be reporting the
alphabet. Berth bonuses are a separate and stricter matter: they are not banked
until the regular season is mathematically over.

## Projections

The site also forecasts. On every build it fits team ratings to the market,
then plays the rest of the season 25,000 times — **freezing every game that
already has a final score** — and scores the real field against the results.
That produces each entrant's chance of winning, chance of cashing, expected
payout in dollars, and a p10–p90 band for their final score.

"The market" means the betting lines on the games ahead. The books post spreads
about three to four weeks out, and each one is a straight statement of how far
apart two teams are *this week* — so the ratings keep up with the season instead
of being pinned to what August thought. Those lines ship in the same nflverse
file the results come from, so this costs no new dependency and no new request.
When no usable lines exist — preseason, or the last week or two, when too few
games remain to compare 32 teams — the fit falls back to the preseason win
totals in `forecast.yaml`. The forecast page names which of the two produced the
numbers you are looking at.

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
- **Schedule** — the NFL slate week by week, opening on the week being played,
  with what each side of every game is worth and who in the pool holds it.
- **Season** — what happened and how it moved, in one place: points scored in
  each week, the standings as they stood after it, points and rank over the
  season, leverage, who is carrying whom, and the gaps between neighbours. The
  old `/weeks/` and `/trends/` addresses forward here, because a year of
  group-chat links points at them.
- **Forecast** — where the model thinks it ends: chance of every finishing
  place, the range of final scores, and every head-to-head.
- **Teams** — every team's leveling factor, record, points generated, and owners.
  Each one links to **that team's own page**: what it has produced and how that
  splits three ways (wins, berth, January), who in the pool is holding it and
  what share of their banked total it is, and its whole season down one column
  — priced by the same builder the schedule page uses, so a game cannot be
  worth one thing there and another here. The bye is named where it falls,
  because a list that jumps from week 5 to week 7 has said nothing about week
  6. All 32 get a page, including the ones nobody picked.
- **Rules** — rendered from `rules.yaml`, the same file the engine reads. It
  opens with the two deadlines and how to pay: picks are due before the
  season's first kickoff and payment by the end of week 1 — both dates read
  off the schedule data, not typed — with the pool's Venmo link and a QR code
  (`venmo:` in the pool's file, validated at load because real money follows
  that URL).

Every one of these exists once **per pool**, under that pool's prefix — team
pages included. The football on a team page is identical in both pools, but the
owners block is not, and one family name on a friends page would be a hole
straight through the wall between them. Only `/assets/` and `/404.html` belong
to the site as a whole.

**Names and teams are clickable wherever they appear** — with no exceptions
left. A team chip goes to that team's page and a person's name goes to theirs:
on the schedule, the teams table, the season page, the rules page, each other's
pages, the leaderboard, and inside the charts, where the names down the side of
the head-to-head grid and the codes written into a contribution bar are links
like everything else.

The leaderboard was the last holdout, and for a real reason: its rows were
themselves links to an entrant page, and an anchor inside an anchor is not a
thing HTML has — browsers recover from it by closing the outer link early,
which would silently cost the row half its click target. So the row stopped
being a link. The name carries it now, stretched over the whole row by the
stylesheet, and the four team chips sit above that: tap anywhere and you get
the entry, tap a chip and you get the team. A test walks every built page and
asserts anchor nesting depth never exceeds one, and another walks the same
pages looking for a name that is printed without being a link.

The markup for both lives in `templates/_links.html`, as `team_chip()` and
`entrant_link()`. It is a macro rather than thirty hand-written anchors because
thirty copies drift, and these had: one chip wore no club colours, two lost
their badge, and the "Owned by" column was the only place an entrant link
forgot its `data-slug` and so never lit up when you said who you were.

Two things are deliberately *not* links, and the code says so where it happens:
a name at the top of its own page, and the hover readout under the head-to-head
grid — that sentence is wiped when the pointer leaves the cell, so moving
towards a link in it is what erases it. Both people are named on the axes just
above, where they are links.

Two links in the masthead lead off it: **Model**, the arithmetic the forecast
is built on, [written out in the open][model]; and the GitHub mark, the source
that builds the page you are reading. The first is cyan because every projected
number on this site is cyan, and this is where those numbers come from. Both
are `MODEL_URL` and `REPO_URL` in `render.py` — facts about the project rather
than about a season, so neither moves when the year rolls over.

[model]: https://gist.github.com/datastx/8670c633fd4e44644bfa99c5d0ba1209

The Schedule page exists because a pool schedule is not an NFL schedule. A win
pays the *winner's own* leveling factor, so the two sides of one game are almost
never worth the same, and the team you need is not always the one favoured. Each
row therefore prices both sides, names who is holding each, and — once you set
*who are you?* — shows what the game is worth to you specifically.

The rail down the left of each row is **swing**: how much the result actually
moves the standings. Adding up everything everybody stands to gain over-rates
chalk, because when a team half the pool owns wins, half the pool rises together
and the order barely changes. Swing subtracts the field's average, so it measures
only the part that separates people — and a game the whole pool is on scores
exactly zero. Games nobody holds are dimmed rather than dropped: they are still
the schedule, they just should not compete for attention.

**Pool games only** drops them altogether, which is what turns a sixteen-game
week into the handful worth reading. It is one attribute on the root element,
so the rule lives in the stylesheet, costs nothing per row, survives switching
week, and is remembered per browser like every other viewer choice. Teams on
bye that nobody holds go with them. A week where the pool genuinely has no side
— which is most of January for most entries — says so instead of going blank,
and the build decides that, because the week already knows how many games the
pool is in.

**Opening a game** shows the rest of what the build already knows: the swing,
what each side pays and to whom, and every entrant with something on it rather
than only you. All of it is in the markup — the stylesheet folds it away only
when `data-js` says there is a client that can unfold it again, which the
inline script in `base.html` sets before first paint. With scripting off every
panel is simply open, which is the honest failure mode for a static site. The
button is the control, because a row full of links is not something a keyboard
can usefully "press"; clicking the row is a convenience on top of it, and it
stands aside for clicks that land on a link or while text is being selected.

**The bracket** sits at the end of the week switcher, after 18. It is a week
section like any other, so `:target`, the switcher and the back button all work
on it for free, and the only new markup is one more link.

A fourteen-team bracket is a fixed shape — three wild-card games a conference,
two divisional, one championship, one Super Bowl — and the only thing that
changes between August and February is how much of it is known. It is drawn at
full size in every state, so the page never reflows underneath whoever is
reading it:

| | what is drawn |
|---|---|
| **Before the first kickoff** | the shape, empty. `playoff_seeds` returns nothing until a game has been played, because with every club 0-0 the tiebreaker ladder falls through to its alphabetical fallback and produces a confident-looking field with Arizona as a one seed. An empty bracket is honest; that one is not. |
| **In season** | the wild-card round from the projected seeds — 2 v 7, 3 v 6, 4 v 5, with the one seed named as being on a bye. Everything past it is drawn as slots that say where their team will come from, because reseeding means the divisional pairings genuinely are not knowable yet. |
| **In January** | the real games, replacing the slots one round at a time, with their scores and their winners. |

Every side carries **what winning that game pays and who in the pool collects
it**, which is the only reason a pool site should draw a bracket rather than
link to one. The wild-card round is the interesting case: the bonus rewards the
upset, so the host is playing for nothing at all, and the bracket says so with
a dimmed zero rather than quietly omitting it.

`bracket.py` knows nothing about pools, entrants or points — it builds the
football, and the renderer prices it. That is what keeps a module about the
NFL's postseason format from growing opinions about money.

Which week opens is decided twice. The build bakes in the week that owns its
fetch instant, and the page re-runs the identical rule against your own clock on
load, so an overnight rollover between deploys still opens on the right week.
Week windows come from kickoff times alone and never from results — the obvious
alternative, "the first week with an unplayed game", sticks forever on one
cancelled game. Everything is in the document at build time and revealed with
`:target`, so every week is a real URL, the back button works, and the page is
fully usable with scripting off.

The Forecast page is three views of one simulation, and none of it costs an
extra run — the numbers were already being computed and thrown away. The
per-game win probabilities on the Schedule page come out of the same run, for
the same reason: they are counted from the simulations themselves rather than
estimated separately, so the two pages can never disagree.

**Where everyone finishes** is a stacked bar per entry across every place,
strongest colour for first. Every bar is the same length because the chances
sum to one, so you compare segment widths rather than bar lengths.

**The range of outcomes** draws each entry's final-score distribution on one
shared scale. A tall narrow curve is a confident forecast and a low wide one
could go anywhere — and where two curves sit on top of each other, the pool is
genuinely close. The shared scale is what makes that overlap mean something, so
the bins are never per-entrant.

**Head to head** gives P(row finishes above column) for every pair, with ties
splitting evenly so opposite cells always add to 100%. The number is printed in
every cell and colour is only reinforcement, so it reads in greyscale and with
any colour vision. The grid is never drawn larger than the size it was
generated at: everything inside an SVG scales with its viewBox, so a
two-person grid stretched across a desktop column would be drawn at four times
life size — postcard cells under an axis caption running off its own axis. Both axes are captioned, and that is not decoration: a grid
of names against the same names looks symmetrical and is not, so without a
caption every cell has two opposite readings and nothing on the page says which
one is on the screen. The caption is one sentence broken across the two edges —
*each entry* down the side, *…finishes above these* along the top — so reading a
cell is reading the sentence. Pointing at one lights up its row and its column
and writes the pair out underneath in full names, because tracing two fingers
across a grid is not a thing anyone should have to do on a phone. The readout
carries both entrants' outright odds alongside the pairwise figure: one number
on its own misleads, because beating somebody 62% of the time reads very
differently when neither of you is likely to win the thing.

The same pairs can be **priced instead of ranked** — a picker beside the
heading swaps the grid for *who out-earns whom*: how often the row's entry took
home more money than the column's, across the same seasons. Both grids are
drawn at build time from one ranking, so the picker is a `hidden` attribute and
nothing else; there is no arithmetic on the client and no way for the two to
disagree.

The money grid breaks the antisymmetry on purpose, and this is the interesting
part. Its opposite cells add to *less* than 100%, because in a pool that pays
three places two mid-table entries both take home nothing in most seasons, and
$0 does not beat $0. Splitting those seasons half each — the way the finishing
grid splits a tie on points — would park every such pair at 50% and bury the
one fact worth reading, which is how rarely money separates them at all. So the
ties are left out of both directions and the readout names them:

> Brian Moore takes home more than Eric Riggs in 41% of simulated seasons,
> less in 27%, and the same in the other 32%.
> Outright, Brian Moore is paid something 70% of the time and Eric Riggs 55%.

Being paid more implies finishing above — the ladder is paid down the ranking —
so the money grid can never lead the finishing one, and the suite asserts it.

**Winning and making money are two different questions**, and the page now says
so before anything else. Chance of winning is first place and nothing else;
expected payout counts every paying place, weighted by how often you finish
there. They routinely disagree — a steady second is worth real money and no
bragging rights at all — and when the two leaders differ the page names both and
says why. Expected profit is the payout less the entry fee, and across the whole
pool it necessarily sums to zero: the pot is exactly what everyone paid in.

The Season page carries two kinds of chart, because they answer two different
questions.

**Compare** is the one you will use. Pick up to six people and their lines come
forward, each in its own colour, assigned in the order you pick them so nobody
changes hue as the season moves. Set *who are you?* in the bar at the top of the
page and the chart opens on your own line every time — that choice also highlights your row on
every other page. It is stored in your browser and goes nowhere else.

It is also stored **per pool**, because a slug from one roster means nothing in
the other: being Brian in the family pool does not make you Brian in the friends
pool, and answering in one must not un-answer the other. Theme and time zone are
the opposite — they describe you rather than a roster, so they follow you across
pools on a single shared key.

**The whole field** draws everyone in a single colour with only the top few
labelled. Thirty distinguishable hues do not exist, and colouring by rank would
make people change colour week to week, so the chart would contradict itself as
the season moved. Hovering any line brings it forward.

Both are rendered as inline SVG at build time; picking only toggles classes, so
with JavaScript off the charts still show the full field.

The site is dark by default and does not follow your operating system — light is
an opt-in from the toggle in the header, remembered per browser.

The two themes are two kickoffs rather than a colour scheme and its inversion.
**Night** is a floodlit stadium: chalk lines on near-black, lime for what has
been banked. **Day** is a one o'clock game on grass — the surface is turf, the
cards sit on it like broadcast graphics, and the lines are *white paint* rather
than ink, because that is what a field is in daylight. It used to be a
parchment page with an olive accent: perfectly readable, and not football.

Every value in both palettes is picked against a contrast target rather than by
eye, and `tests/test_theme.py` parses the tokens out of the stylesheet and
holds them to it — body text clears AA on the turf, on the mown stripe and on a
card; every semantic colour clears AA as type on a card and the large-text
threshold on the field; and banked, modelled and trouble stay at least 30° apart
in hue, which is a hue check on purpose, since a green and a teal of identical
brightness are 1.03:1 apart by luminance and unmistakable to a reader. The one
thing deliberately *below* a text threshold is the paint, and that is asserted
too: a field marking that reached text contrast would be competing with the
scoreboard on top of it.

## The field

The background is a football field, one end zone at the top of the screen and
the other at the bottom, drawn to scale with yard lines, hash marks, painted
numbers and both wordmarks. It is a `<canvas>` rather than an SVG or a stack of
gradients because the numbers have to rotate to face their own sideline and the
hash marks number in the hundreds — and because it is repainted only when the
viewport or the theme actually changes, never on scroll.

It runs away from the reader rather than across, which is the one orientation
that holds up on both a phone and a desktop: a portrait viewport is very nearly
the proportion of a real field seen from behind the goalposts. Every colour it
paints with is a CSS custom property (`--paint-chalk`, `--paint-endzone`, and
so on) read back through `getComputedStyle`, so the drawing code names marks by
their job and never knows which theme is on. The alphas are tuned per theme
rather than shared, because chalk on a night field and ink on a day field do not
read at the same strength.

The field does not move. It is anchored to the viewport rather than the
document, so scrolling never shifts it and it is drawn once per resize. With
scripting off, the stylesheet's mown turf carries the page on its own.

**The chain crew** does move: two marks that ride the scroll from your own goal
line to the far end zone, with the yard they are standing on written in the
sideline — own 34, midfield, opp 12, touchdown. Inside the twenty they turn
from floodlight green to orange, and reaching the far end zone sets off a flare,
which is the only thing on this site you can win by scrolling.

The first version of this was the broadcast first-down line: one bright rule
from sideline to sideline. Across an empty field that is exactly right, and
across a paragraph it is a strike-through — it landed on whatever sentence you
happened to be reading and cut it in half. So the middle came out and the ends
stayed, which is where the chain crew stands anyway. The marks reach in as far
as the edge of the text column and stop: on a wide screen that is a good long
run, on a phone it is a tick at the very edge of the glass, and at no width does
anything cross anything worth reading. Everything about them is one transform on
one element, read inside an animation frame rather than inside the scroll event,
so a fast flick queues one repaint instead of forty — and `prefers-reduced-motion`
stands the whole thing down.

Panels and cards settle into place as you reach them. The hidden state is added
by the client and removed on first sight, so nothing is ever invisible without
JavaScript — and anything already on screen when the script runs is left alone,
because that would be a flicker rather than an entrance. Headings and body copy
are deliberately never animated: a title that assembles itself while its own
paragraph is already there makes a section look out of order.

Four more pieces of motion, each earning its keep:

| | |
|---|---|
| **Sorting a table** | The rows glide to their new places instead of teleporting. FLIP: they are already where they belong, so each one is offset back to where it was and released — one layout read, then pure compositing. Watching your own row travel to fourth is worth more than finding it already there. |
| **The head-to-head grid** | Deals itself in on the diagonal. Every cell carries its distance from the corner as `--i` and holds for that long, so the whole grid arrives as one wave instead of a hundred cells in reading order. |
| **The theme toggle** | The floodlights come on from the switch that asked for them: a circle of the new palette opening out of the button, via a View Transition with a `clip-path` the client sizes to the far corner. Anything carrying its own `view-transition-name` is suppressed for the length of the wipe, or it would sit outside the circle and change palette on its own schedule. |
| **A row under the pointer** | One pass of a floodlight across it. On the way in only — a sheen that ran continuously would be the brightest moving thing on a page whose whole job is to hold still and be read. |

## Saying what the words mean

Half the vocabulary on this site means something specific here and something
vaguer everywhere else. *On the table* is not "points available", *locked in* is
not "guaranteed to you", and *expected $* is emphatically not what anybody is
going to be paid. Every one of those now carries an **i** beside it that opens
the full definition on hover, on focus, or on a tap.

The definitions live in `glossary.py`, once, and the templates reference them by
key — so a term cannot be explained one way on the schedule page and another way
on the forecast. They are generated from a `Season` rather than written as fixed
prose, because the numbers that make them concrete are configurable: a
definition that says "the top three" when `rules.yaml` pays two would be worse
than no definition. `/rules/` renders the whole glossary as a table, which is
also where the definitions still are for anyone the popovers cannot reach.

Each definition is written twice on purpose. Once inside the button as
visually-hidden text, which makes it the button's accessible name — a screen
reader reads "On the table: the most the whole pool could bank…" and has nothing
to open. Once as the popover a sighted reader hovers. The popover is
`position: fixed` and placed by the client, because several of these live inside
tables and a table is a clipping context.

## Byes

A bye is the one thing a schedule cannot show you: there is no row to render, so
an entrant whose team is off just finds a quiet week with no explanation for it.
Each regular-season week therefore names the teams that are not playing —
owners first, and struck through rather than merely dimmed, because dim already
means "has not scored yet" everywhere else on the site. An entrant's own page
names whichever of their four are off next week, right beside the next-week
ceiling that the bye is the reason for.

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

Asset URLs carry a content fingerprint — `/assets/site.css?v=dac5cb39`. GitHub
Pages pins every response to `max-age=600` and gives no way to change it, so for
ten minutes after a deploy a returning visitor can hold the previous stylesheet
against markup fetched a moment ago, which looks exactly like a layout bug. The
stamp is a hash of the file's *contents*, not the build time, so a rebuild on a
day when only the scores changed leaves every asset URL — and therefore every
warm cache — untouched.

With more than one pool, that same `url` filter resolves against two prefixes,
and the rule is one sentence: **`/assets/` belongs to the site, everything else
belongs to the pool.** Keep `/assets/` the only exception. A page URL that needs
to be site-relative and is not under it would be silently pool-scoped and 404 on
the non-root pool only, in production only — which is why the build check greps
the *nested* pool's markup as well as the root's.

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

`daily.yml` runs one `pool build`, which emits the whole site — every pool, one
copy of the assets. Adding a pool therefore needs no workflow change at all,
because the pool list lives on disk rather than in a flag.

After that `.github/workflows/daily.yml` builds on the football calendar, plus
on demand from the Actions tab. Every schedule is written on the Eastern clock
(`timezone: America/New_York`), so nothing drifts when the season crosses the
daylight-saving change, and every one is restricted to September–February:

| When (Eastern) | Cron | What it is for |
| --- | --- | --- |
| Sunday, hourly 14:37–23:37 | `37 14-23 * 1,2,9-12 0` | 84% of the season's games, published wave by wave |
| Thu/Fri/Sat, hourly 19:37–23:37 | `37 19-23 * 1,2,9-12 4,5,6` | Thursday night, December Saturdays, the playoff Saturdays, Thanksgiving and Christmas |
| Nightly 01:37 and 03:37 | `37 1,3 * 1,2,9-12 *` | Every night game; 03:37 covers a 22:00 Monday doubleheader |
| 1st and 15th, 12:37, year round | `37 12 1,15 * *` | Keepalive — see below |

The sizing comes from two upstream facts: a game runs about 3h30m from kickoff
to final, and the nflverse feed commits every 15–90 minutes. Scored against the
real 2025 and 2026 schedules with worst-case feed lag, the site ends up at most
3.1 hours behind any final and typically 2.1. Publishing mid-slate is safe —
unplayed games do not score, so an afternoon build shows fewer points, never
wrong ones.

Both test suites gate the deploy — if a scoring test breaks, the site is not
republished and yesterday's good version stays up.

The keepalive is not decoration. GitHub disables scheduled workflows in a
public repository after 60 days with no **commit** to it — runs, issues and
tags do not count — and a season-only schedule leaves a March-to-September gap
that trips it. So a run on the 1st and 15th commits a stamp to
`data/last-keepalive` whether or not the data moved, and does it even when the
build failed. Without it the schedule dies quietly in April and the site is
still showing February's scoreboard on opening weekend.
