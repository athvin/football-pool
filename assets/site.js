/**
 * Client-side behaviour for the pool site.
 *
 * There is deliberately very little of it: every number on every page is
 * server-rendered, so this only handles the three things that genuinely depend
 * on the viewer — their theme, their time zone, and motion on first paint.
 *
 * The logic is factored into pure functions with no DOM access so it can be
 * unit tested directly; `init()` is the only part that touches the document.
 */

export const THEME_KEY = 'pool-theme';
export const TZ_KEY = 'pool-tz';
export const ME_KEY = 'pool-me';
export const DETAIL_KEY = 'pool-detail';
export const SLATE_KEY = 'pool-slate';
export const COMPARE_KEY = 'pool-compare';
export const DEFAULT_TZ = 'America/New_York';
export const DEFAULT_THEME = 'dark';

/**
 * Namespace a storage key to one pool.
 *
 * localStorage is per *origin*, not per path, so two pools on one Pages site
 * share a single store. Theme, time zone and density describe the viewer and
 * should follow them across pools — those keys stay global. Identity does not:
 * `pool-me` and `pool-compare` hold entrant slugs, which mean nothing in the
 * other roster. Unscoped, opening the second pool finds the stored slug absent
 * from its picker, writes '' back over it, and silently forgets who you are in
 * the first one.
 *
 * The root pool's scope is the empty string, deliberately — it leaves the key a
 * returning visitor already has exactly where it was. Scoping is by slug and
 * never by year, so the existing self-healing on season rollover still works
 * instead of stranding a dead key in every browser.
 */
export function scopedKey(key, scope) {
  return scope ? `${key}:${scope}` : key;
}

/**
 * Colours for the comparison chart, assigned in the order people are picked.
 *
 * Pick order rather than a fixed per-entrant colour, so the first person you
 * choose is always the first colour and nobody's line changes hue as the
 * standings move. Six is the cap: beyond that the hues stop being reliably
 * distinguishable, which is the whole reason to have distinct ones.
 */
export const PICK_COLORS = [
  '#c6ff3d', '#4dd8e6', '#ff9f1c', '#b48ce8', '#ff6b35', '#5ee6a8',
];

/**
 * Flip between themes.
 *
 * Dark is the site's default, unconditionally — it does not follow the
 * operating system — so anything that is not an explicit "light" is dark, and
 * the first click always lands on light.
 */
export function nextTheme(current) {
  return current === 'light' ? DEFAULT_THEME : 'light';
}

/** How a footer stamp reads: "Feb 9, 2:30 PM EST". */
export const STAMP_FORMAT = {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
};

/**
 * How a kickoff reads: "Sun, Sep 13, 1:00 PM EDT".
 *
 * Football is scheduled by weekday — Thursday night, Sunday one o'clock, Monday
 * night — and a bare "Sep 13" makes you count on your fingers. The weekday has
 * to come from the same Intl call as the rest, never a server-rendered span: a
 * Sunday 8:20pm Eastern kickoff is *Monday* in UTC, so a baked weekday would be
 * wrong for anyone who moves the picker.
 */
export const KICKOFF_FORMAT = { weekday: 'short', ...STAMP_FORMAT };

// One formatter per (locale, zone, format). The schedule page carries close to
// 300 stamps and repaints all of them on every zone change; constructing an
// Intl.DateTimeFormat each time is the most expensive thing on the page.
const formatters = new Map();

function formatterFor(locale, timeZone, format) {
  // Keyed on the whole format object: keying on one field silently collides
  // the day a third format shows up.
  const key = `${locale}|${timeZone}|${JSON.stringify(format)}`;
  let found = formatters.get(key);
  if (!found) {
    // Only successful constructions are cached, so an invalid zone keeps
    // falling through to the raw ISO string instead of being remembered.
    found = new Intl.DateTimeFormat(locale, { timeZone, ...format });
    formatters.set(key, found);
  }
  return found;
}

/**
 * Render a UTC timestamp in the viewer's chosen zone.
 *
 * Falls back to the original string rather than throwing, because a bad stored
 * time zone should never blank out the "data through" stamp.
 */
export function formatTimestamp(iso, timeZone, locale = 'en-US', format = STAMP_FORMAT) {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  try {
    return formatterFor(locale, timeZone, format).format(when);
  } catch {
    return iso;
  }
}

/** Past this, the data is old enough that the badge should say so in red. */
export const STALE_AFTER_HOURS = 24;

/**
 * How long ago something happened, in the units a person would use.
 *
 * Deliberately coarse — a scoreboard refreshed twice a day does not need
 * minutes, and "13h ago" is a more useful answer than "13h 42m ago". A stamp
 * in the future reads as "just now" rather than as a negative age, because the
 * only way to get one is a clock disagreement and that is not the reader's
 * problem.
 */
export function relativeAge(iso, nowMs) {
  const when = Date.parse(iso);
  if (!Number.isFinite(when)) return null;

  const minutes = Math.floor((nowMs - when) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** Is this stamp old enough to be worth flagging? */
export function isStale(iso, nowMs, hours = STALE_AFTER_HOURS) {
  const when = Date.parse(iso);
  if (!Number.isFinite(when)) return false;
  return nowMs - when > hours * 3600000;
}

/** Is this a time zone the browser will accept? */
export function isValidTimeZone(tz) {
  if (!tz) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/**
 * How far a circle centred on `origin` has to grow to cover the viewport.
 *
 * The far corner is the one that matters, and which corner that is depends on
 * where the origin sits — so take the longer distance on each axis and put
 * them together. Used by the theme wipe, which must clear the screen exactly
 * once and never leave a crescent of the old palette in a corner.
 */
export function sweepRadius(origin, viewport) {
  const dx = Math.max(origin.x, viewport.width - origin.x);
  const dy = Math.max(origin.y, viewport.height - origin.y);
  return Math.hypot(dx, dy);
}

export function easeOutCubic(t) {
  const clamped = Math.min(Math.max(t, 0), 1);
  return 1 - Math.pow(1 - clamped, 3);
}

// ---------------------------------------------------------------------------
// The gridiron
// ---------------------------------------------------------------------------

/**
 * A regulation field, in yards: two ten-yard end zones and the hundred
 * between them. The page draws it running away from the reader — near end
 * zone at the top of the screen, far end zone at the bottom — because that is
 * the one orientation that holds up on both a phone and a desktop. A portrait
 * viewport is very nearly the proportion of a real field seen from behind the
 * goalposts, and scrolling down the page then genuinely moves you downfield.
 */
export const FIELD_YARDS = 120;
export const END_ZONE_YARDS = 10;

/** Where the field sits inside a viewport of the given size. */
export function fieldGeometry(width, height) {
  return {
    width,
    height,
    // One yard, measured along the length of the field.
    yard: height / FIELD_YARDS,
    // The sidelines are inset to leave a margin the way a stadium does. The
    // cap stops a wide desktop viewport from pushing them absurdly far in.
    inset: Math.min(width * 0.055, 26),
  };
}

/** Screen y for a point `yards` from the back of the near end zone. */
export function yardToY(geom, yards) {
  return yards * geom.yard;
}

/**
 * The number painted at a yard line, in the way a field paints it.
 *
 * Fields count up to the fifty from both ends, so the mark is the distance to
 * the nearer goal line — 20 yards in is a 10, midfield is a 50.
 */
export function markerNumber(yards) {
  return 50 - Math.abs(yards - FIELD_YARDS / 2);
}

/** Inside the opponent's twenty, measured from your own goal line. */
export const RED_ZONE = 80;

/**
 * How a spot on the field reads out loud: "own 34", "midfield", "opp 12".
 *
 * ``yards`` is measured from the near goal line, so 0 is your own goal line
 * and 100 is the far end zone.
 */
export function driveLabel(yards) {
  if (yards <= 0.5) return 'Own goal line';
  if (yards >= 99.5) return 'Touchdown';
  if (yards >= 49.5 && yards <= 50.5) return 'Midfield';
  const spot = Math.round(yards);
  return spot < 50 ? `Own ${spot}` : `Opp ${100 - spot}`;
}

/**
 * How far down the page the reader is, as a fraction.
 *
 * A page too short to scroll has nowhere to drive to, so it reports zero
 * rather than dividing by it.
 */
export function scrollProgress(scrollTop, scrollMax) {
  if (!(scrollMax > 0)) return 0;
  return Math.min(Math.max(scrollTop / scrollMax, 0), 1);
}

/** The paint tokens, read off the document so the theme owns every colour. */
export function fieldPalette(styles) {
  const read = (name) => styles.getPropertyValue(name).trim();
  return {
    turfA: read('--turf-a') || '#070b0e',
    turfB: read('--turf-b') || '#0a1014',
    chalk: read('--paint-chalk'),
    chalkStrong: read('--paint-chalk-strong'),
    number: read('--paint-number'),
    hash: read('--paint-hash'),
    endZone: read('--paint-endzone'),
    wordmark: read('--paint-wordmark'),
    pylon: read('--paint-pylon'),
    display: read('--display') || 'sans-serif',
  };
}

/**
 * Paint the field.
 *
 * Takes a plain 2D-context-shaped object rather than reaching for a canvas
 * itself, which keeps every decision here — where the goal lines land, which
 * numbers get painted, when the hash marks are too dense to be worth drawing
 * — testable without a rendering engine.
 */
export function drawField(ctx, geom, paint, marks = {}) {
  const { width, height, yard, inset } = geom;
  const left = inset;
  const right = width - inset;
  const y = (yards) => yardToY(geom, yards);

  ctx.clearRect(0, 0, width, height);

  // Mown turf, banded every five yards so the stripes and the yard lines are
  // the same rhythm rather than two rhythms beating against each other.
  for (let band = 0; band < FIELD_YARDS / 5; band += 1) {
    ctx.fillStyle = band % 2 === 0 ? paint.turfA : paint.turfB;
    ctx.fillRect(0, y(band * 5), width, yard * 5 + 1);
  }

  // Both end zones, tinted.
  ctx.fillStyle = paint.endZone;
  ctx.fillRect(0, 0, width, y(END_ZONE_YARDS));
  ctx.fillRect(0, y(FIELD_YARDS - END_ZONE_YARDS), width, y(END_ZONE_YARDS));

  const line = (yards, color, thickness) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = thickness;
    ctx.beginPath();
    ctx.moveTo(left, y(yards));
    ctx.lineTo(right, y(yards));
    ctx.stroke();
  };

  // Yard lines every five, then the goal lines over the top of them.
  for (let yards = 15; yards <= FIELD_YARDS - 15; yards += 5) {
    line(yards, paint.chalk, 1);
  }
  line(END_ZONE_YARDS, paint.chalkStrong, 2);
  line(FIELD_YARDS - END_ZONE_YARDS, paint.chalkStrong, 2);

  // Sidelines and end lines: the rectangle the game is played inside.
  ctx.strokeStyle = paint.chalkStrong;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(left, 0.75, right - left, height - 1.5);

  // Hash marks, one per yard, in the four rows a field carries them: just
  // inside each sideline and either side of the middle. Skipped outright when
  // a yard is too few pixels for the ticks to be anything but noise.
  if (yard >= 5) {
    const span = right - left;
    const tick = Math.max(span * 0.012, 4);
    const rows = [left + 4, left + span * 0.347, left + span * 0.653, right - 4 - tick];
    ctx.strokeStyle = paint.hash;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let yards = END_ZONE_YARDS + 1; yards < FIELD_YARDS - END_ZONE_YARDS; yards += 1) {
      if (yards % 5 === 0) continue; // already a full yard line
      for (const x of rows) {
        ctx.moveTo(x, y(yards));
        ctx.lineTo(x + tick, y(yards));
      }
    }
    ctx.stroke();
  }

  // The painted numbers, one pair every ten yards, each turned to face its
  // own sideline the way they are painted on a real field.
  const size = Math.min(Math.max(width * 0.038, 15), 46);
  ctx.fillStyle = paint.number;
  ctx.font = `800 ${size}px ${paint.display}`;
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  for (let yards = 20; yards <= FIELD_YARDS - 20; yards += 10) {
    const text = String(markerNumber(yards));
    for (const side of [-1, 1]) {
      const x = side < 0 ? left + (right - left) * 0.13 : right - (right - left) * 0.13;
      ctx.save();
      ctx.translate(x, y(yards));
      ctx.rotate((side * Math.PI) / 2);
      ctx.fillText(text, 0, 0);
      ctx.restore();
    }
  }

  // The wordmarks in the end zones. Upright in both, deliberately: a real far
  // end zone reads upside down from here, and an unreadable word is a worse
  // joke than an unfaithful one.
  const endZoneText = (text, centre) => {
    if (!text) return;
    const cap = Math.min(y(END_ZONE_YARDS) * 0.5, (right - left) / (text.length + 2));
    ctx.font = `800 ${Math.max(cap, 10)}px ${paint.display}`;
    ctx.fillStyle = paint.wordmark;
    ctx.save();
    ctx.translate(width / 2, centre);
    ctx.fillText(text.toUpperCase(), 0, 0);
    ctx.restore();
  };
  endZoneText(marks.near, y(END_ZONE_YARDS / 2));
  endZoneText(marks.far, y(FIELD_YARDS - END_ZONE_YARDS / 2));

  // Pylons: the eight orange corners of the two end zones.
  ctx.fillStyle = paint.pylon;
  const pylon = Math.max(yard * 0.35, 3);
  for (const yards of [0, END_ZONE_YARDS, FIELD_YARDS - END_ZONE_YARDS, FIELD_YARDS]) {
    for (const x of [left, right]) {
      ctx.fillRect(x - pylon / 2, y(yards) - pylon / 2, pylon, pylon);
    }
  }
}

/** Value part-way through a count-up, used by the scoreboard odometer. */
export function countUpValue(target, progress) {
  return target * easeOutCubic(progress);
}

/**
 * Push overlapping endpoint labels apart, keeping their vertical order.
 *
 * Two people finishing a week on the same score put their labels in exactly the
 * same place. The markers stay on the true values; only the text moves.
 */
export function spreadLabels(items, gap = 14, top = -Infinity, bottom = Infinity) {
  let previous = -Infinity;
  const placed = [...items]
    .sort((a, b) => a.y - b.y)
    .map(({ slug, y }) => {
      const yOut = Math.max(y, previous + gap);
      previous = yOut;
      return { slug, y: yOut };
    });

  // If the stack overflowed the plot, slide the whole run back up — the same
  // correction the Python `_spread` has always applied. Without it, labels for
  // lines finishing near the chart bottom were pushed past the viewBox and
  // clipped invisible.
  if (placed.length && bottom < Infinity && placed[placed.length - 1].y > bottom) {
    const shift = Math.min(placed[placed.length - 1].y - bottom, placed[0].y - top);
    if (shift > 0) return placed.map((p) => ({ slug: p.slug, y: p.y - shift }));
  }
  return placed;
}

/**
 * Order two table cells.
 *
 * Numeric when both sides genuinely are numbers, lexical otherwise — so a
 * points column sorts 9 before 10, while a "0-0" record column falls back to
 * text instead of being silently read as zero.
 */
export function compareValues(a, b) {
  const left = String(a).trim();
  const right = String(b).trim();
  const nl = Number(left);
  const nr = Number(right);
  if (left !== '' && right !== '' && Number.isFinite(nl) && Number.isFinite(nr)) {
    return nl - nr;
  }
  return left.localeCompare(right, 'en', { numeric: true, sensitivity: 'base' });
}

/** The value a cell sorts on: an explicit data-value if present, else its text. */
export function cellValue(row, index) {
  const cell = row.children[index];
  if (!cell) return '';
  const explicit = cell.getAttribute('data-value');
  return explicit === null ? cell.textContent : explicit;
}

/** Reorder a table body in place. Returns the rows in their new order. */
export function sortTable(table, index, direction) {
  const body = table.tBodies[0];
  if (!body) return [];
  const rows = Array.from(body.rows);
  rows.sort((a, b) => direction * compareValues(cellValue(a, index), cellValue(b, index)));
  for (const row of rows) body.appendChild(row);
  return rows;
}

/** Every row's position on screen right now, keyed by the row itself. */
export function rowTops(table) {
  const body = table.tBodies[0];
  if (!body) return new Map();
  return new Map(Array.from(body.rows, (row) => [row, row.getBoundingClientRect().top]));
}

/**
 * Which rows moved between two readings, and how far.
 *
 * A row that was not in the first reading is skipped rather than assumed to
 * have come from the top of the table, and sub-pixel drift is not movement —
 * a re-sort that leaves the order alone should animate nothing at all.
 */
export function flipShifts(before, after) {
  const shifts = [];
  for (const [row, top] of after) {
    const was = before.get(row);
    if (was === undefined) continue;
    const dy = was - top;
    if (Math.abs(dy) >= 1) shifts.push({ row, dy });
  }
  return shifts;
}

/**
 * Rows slide to their new places rather than teleporting into them.
 *
 * First, Last, Invert, Play: by the time this runs the rows are already where
 * they belong, so each one is offset back to where it was and let go. The
 * offset is a transform, so the whole re-order costs one layout read and then
 * nothing else — the browser is compositing, not reflowing, for the rest of it.
 *
 * Sorting a table is the one place on the site where the reader has asked for
 * a rearrangement, and watching their own row travel to fourth is worth more
 * than seeing it already there.
 */
export function glideRows(table, before) {
  for (const { row, dy } of flipShifts(before, rowTops(table))) {
    row.animate?.(
      [{ transform: `translateY(${dy.toFixed(1)}px)` }, { transform: 'none' }],
      { duration: 420, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' },
    );
  }
}

/**
 * Where a definition popover goes, given what it is explaining.
 *
 * Below the button by default and above it when there is no room below, then
 * slid sideways until it fits — the popover is the same width as a phone is
 * wide, so on a phone it is effectively always being slid. Everything is in
 * viewport coordinates because the popover is positioned `fixed`: it has to
 * escape the table cell it is very often sitting inside.
 */
export function tooltipPosition(anchor, size, viewport, gap = 8) {
  const below = anchor.bottom + gap;
  const above = anchor.top - gap - size.height;
  // Flip up only when the tooltip genuinely does not fit below *and* fits
  // above; a long definition near the bottom of a short viewport fits neither,
  // and pinning it to the top edge beats hanging it off the bottom.
  const flip = below + size.height > viewport.height && above >= 0;
  const top = flip ? above : Math.min(below, Math.max(viewport.height - size.height - gap, gap));

  const centred = anchor.left + anchor.width / 2 - size.width / 2;
  const left = Math.min(Math.max(centred, gap), Math.max(viewport.width - size.width - gap, gap));
  return { left, top, flipped: flip };
}

/** Storage that silently no-ops when it is unavailable (private browsing). */
export function safeStorage(store) {
  return {
    get(key) {
      try {
        return store.getItem(key);
      } catch {
        return null;
      }
    },
    set(key, value) {
      try {
        store.setItem(key, value);
      } catch {
        /* nothing sensible to do */
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Gameday: scenario maths and the optional live ESPN overlay
// ---------------------------------------------------------------------------

export const ESPN_SCOREBOARD =
  'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard';
export const ESPN_SCOREBOARD_WEB =
  'https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard';
export const LIVE_POLL_MS = 20_000;
export const PREGAME_POLL_MS = 180_000;

/** ESPN and nflverse use different abbreviations for two clubs. */
export function normalizeEspnTeam(team) {
  return ({ WSH: 'WAS', JAC: 'JAX', LA: 'LAR' })[team] || team;
}

/** Reduce the large scoreboard response to the live facts this page can show. */
export function parseEspnScoreboard(payload) {
  const games = [];
  for (const event of payload?.events || []) {
    const competition = event?.competitions?.[0];
    if (!competition) continue;
    const home = competition.competitors?.find((team) => team.homeAway === 'home');
    const away = competition.competitors?.find((team) => team.homeAway === 'away');
    if (!home || !away) continue;
    const situation = competition.situation || {};
    const possession = competition.competitors?.find(
      (team) => String(team.id) === String(situation.possession),
    );
    const state = event?.status?.type?.state || 'pre';
    const period = Number(event?.status?.period || 0);
    const displayClock = event?.status?.displayClock || '';
    games.push({
      id: String(event.id),
      away: normalizeEspnTeam(away.team?.abbreviation),
      home: normalizeEspnTeam(home.team?.abbreviation),
      awayScore: String(away.score ?? '0'),
      homeScore: String(home.score ?? '0'),
      state,
      clock: state === 'in' ? `Q${period} ${displayClock}`.trim() : '',
      down: situation.downDistanceText || '',
      possession: possession ? normalizeEspnTeam(possession.team?.abbreviation) : '',
      redZone: Boolean(situation.isRedZone),
      lastPlay: situation.lastPlay?.text || '',
    });
  }
  return games;
}

/** Poll fast only during live football, gently while the week's games wait. */
export function livePollDelay(games) {
  if (games.some((game) => game.state === 'in')) return LIVE_POLL_MS;
  if (games.some((game) => game.state === 'pre')) return PREGAME_POLL_MS;
  return 0;
}

/** Parse only choices that still name a game and legal outcome in this build. */
export function parseScenarioHash(hash, games) {
  const selections = {};
  if (!String(hash).startsWith('#scenario=')) return selections;
  const legal = new Map(games.map((game) => [
    String(game.id),
    new Set([game.away, game.home, ...(game.tie ? ['TIE'] : [])]),
  ]));
  let decoded;
  try {
    decoded = decodeURIComponent(String(hash).slice('#scenario='.length));
  } catch {
    return selections;
  }
  for (const token of decoded.split(',')) {
    const split = token.lastIndexOf(':');
    if (split <= 0) continue;
    const id = token.slice(0, split);
    const outcome = token.slice(split + 1);
    if (legal.get(id)?.has(outcome)) selections[id] = outcome;
  }
  return selections;
}

export function serializeScenario(selections, games) {
  const calls = games
    .filter((game) => selections[String(game.id)])
    .map((game) => `${game.id}:${selections[String(game.id)]}`);
  return calls.length ? `#scenario=${calls.join(',')}` : '';
}

/** Add called outcomes to banked points, then apply competition ranking. */
export function scenarioStandings(data, selections) {
  const totals = new Map(data.entrants.map((entrant) => [entrant.slug, Number(entrant.banked)]));
  for (const game of data.games) {
    const outcome = selections[String(game.id)];
    if (!outcome) continue;
    for (const entrant of data.entrants) {
      const gain = Number(game.points?.[entrant.slug]?.[outcome] || 0);
      totals.set(entrant.slug, totals.get(entrant.slug) + gain);
    }
  }
  return data.entrants
    .map((entrant) => ({ ...entrant, total: totals.get(entrant.slug) }))
    .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name))
    .map((entrant, _index, all) => ({
      ...entrant,
      rank: 1 + all.filter((other) => other.total > entrant.total).length,
    }));
}

export function scenarioPreset(data, preset, meSlug = '') {
  if (preset === 'reset') return {};
  const out = {};
  for (const game of data.games) {
    if (preset === 'likely') out[game.id] = game.favorite;
    if (preset === 'chaos') out[game.id] = game.chaos;
    if (preset === 'dream' && game.dream?.[meSlug]) out[game.id] = game.dream[meSlug];
  }
  return out;
}

function paintGamedayOrder(doc, win) {
  const grid = doc.querySelector('[data-gameday-cards]');
  if (!grid) return;
  const slug = doc.documentElement.dataset.me || '';
  const cards = Array.from(grid.querySelectorAll('[data-gameday-card]'));
  const before = new Map(cards.map((card) => [card, card.getBoundingClientRect()]));
  cards.sort((a, b) => {
    const priority = (card) => Number(
      card.querySelector(`.rooting-readout[data-slug="${slug}"]`)?.dataset.priority
        || card.dataset.drama || 0,
    );
    return priority(b) - priority(a);
  });
  for (const card of cards) grid.append(card);
  if (win.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  for (const card of cards) {
    const was = before.get(card);
    const now = card.getBoundingClientRect();
    if (!was.height || !now.height) continue;
    const shift = was.top - now.top;
    if (Math.abs(shift) < 1) continue;
    card.animate?.(
      [{ transform: `translateY(${shift.toFixed(1)}px)` }, { transform: 'none' }],
      { duration: 420, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' },
    );
  }
}

function initScenario(doc, win) {
  const script = doc.querySelector('#gameday-data');
  const root = doc.querySelector('[data-scenario]');
  if (!script || !root) return;
  let data;
  try {
    data = JSON.parse(script.textContent);
  } catch {
    return;
  }
  let selections = parseScenarioHash(doc.location?.hash || '', data.games);
  let previousMeRank = null;

  const paint = () => {
    const standings = scenarioStandings(data, selections);
    const board = root.querySelector('[data-scenario-board]');
    const rows = new Map(Array.from(board?.children || [], (row) => [row.dataset.slug, row]));
    for (const entrant of standings) {
      const row = rows.get(entrant.slug);
      if (!row) continue;
      row.querySelector('.scenario-rank').textContent = entrant.rank;
      row.querySelector('.scenario-total').textContent = entrant.total.toFixed(2);
      board.append(row);
    }
    for (const fieldset of root.querySelectorAll('[data-scenario-game]')) {
      const chosen = selections[fieldset.dataset.scenarioGame];
      for (const button of fieldset.querySelectorAll('[data-scenario-choice]')) {
        button.setAttribute('aria-pressed', String(button.dataset.scenarioChoice === chosen));
      }
    }
    const me = doc.documentElement.dataset.me || '';
    const meRank = standings.find((entrant) => entrant.slug === me)?.rank ?? null;
    if (previousMeRank !== null && previousMeRank > 1 && meRank === 1
        && !win.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      doc.documentElement.classList.remove('is-goal-line');
      // Force a new animation even if two calls reach first in quick succession.
      void doc.documentElement.offsetWidth;
      doc.documentElement.classList.add('is-goal-line');
      win.setTimeout(() => doc.documentElement.classList.remove('is-goal-line'), 850);
    }
    previousMeRank = meRank;
    const hash = serializeScenario(selections, data.games);
    win.history?.replaceState?.(null, '', `${doc.location?.pathname || ''}${hash}`);
  };

  root.addEventListener('click', (event) => {
    const choice = event.target.closest?.('[data-scenario-choice]');
    if (choice) {
      const game = choice.closest('[data-scenario-game]').dataset.scenarioGame;
      selections[game] = selections[game] === choice.dataset.scenarioChoice
        ? undefined : choice.dataset.scenarioChoice;
      if (!selections[game]) delete selections[game];
      paint();
      return;
    }
    const preset = event.target.closest?.('[data-scenario-preset]')?.dataset.scenarioPreset;
    if (preset) {
      const me = doc.documentElement.dataset.me || '';
      const status = root.querySelector('[data-scenario-status]');
      if (preset === 'dream' && !me) {
        if (status) status.textContent = 'Choose who you are above to build your dream slate.';
        return;
      }
      selections = scenarioPreset(data, preset, me);
      if (status) status.textContent = '';
      paint();
    }
  });

  root.querySelector('[data-scenario-share]')?.addEventListener('click', async () => {
    const status = root.querySelector('[data-scenario-status]');
    try {
      const copy = win.navigator?.clipboard?.writeText;
      if (typeof copy !== 'function') throw new Error('clipboard unavailable');
      await copy.call(win.navigator.clipboard, win.location?.href || doc.location?.href);
      if (status) status.textContent = 'Scenario link copied.';
    } catch {
      if (status) status.textContent = 'Copy the scenario URL from your address bar.';
    }
  });

  doc.querySelector('[data-me-select]')?.addEventListener('change', () => {
    previousMeRank = null;
    paint();
  });
  paint();
}

function paintLiveGames(doc, games) {
  for (const game of games) {
    const card = doc.querySelector(
      `[data-gameday-card][data-away="${game.away}"][data-home="${game.home}"]`,
    );
    if (!card || game.state === 'pre') continue;
    const strip = card.querySelector('[data-live-game]');
    if (!strip) continue;
    strip.hidden = false;
    card.querySelector('[data-live-status]').textContent =
      game.state === 'post' ? 'Final' : game.clock;
    card.querySelector('[data-live-score]').textContent =
      `${game.away} ${game.awayScore} · ${game.home} ${game.homeScore}`;
    const situation = [
      game.possession ? `${game.possession} ball` : '',
      game.down,
      game.redZone ? 'RED ZONE' : '',
    ].filter(Boolean).join(' · ');
    card.querySelector('[data-live-situation]').textContent = situation;
    const detail = card.querySelector('[data-live-detail]');
    const lastPlay = card.querySelector('[data-live-last-play]');
    if (detail && lastPlay && game.lastPlay) {
      detail.hidden = false;
      lastPlay.textContent = game.lastPlay;
    }
  }
}

async function fetchEspnGames(win, url = ESPN_SCOREBOARD) {
  let response = await win.fetch(url, { cache: 'no-store' });
  // ESPN has occasionally rejected non-browser-shaped traffic on the older
  // host while serving the same public response from site.web.api. Keep that
  // narrowly scoped fallback here rather than making every caller know it.
  if (response.status === 403 && url.startsWith(ESPN_SCOREBOARD)) {
    response = await win.fetch(url.replace(ESPN_SCOREBOARD, ESPN_SCOREBOARD_WEB), {
      cache: 'no-store',
    });
  }
  if (!response.ok) throw new Error(`ESPN ${response.status}`);
  return parseEspnScoreboard(await response.json());
}

function renderLiveHarness(doc, root, games) {
  const list = root.querySelector('[data-live-harness-games]');
  if (!list) return;
  list.textContent = '';
  for (const game of games) {
    const row = doc.createElement('article');
    row.className = `live-lab-game is-${game.state}`;
    const matchup = doc.createElement('strong');
    matchup.textContent = `${game.away} ${game.awayScore} · ${game.home} ${game.homeScore}`;
    const state = doc.createElement('span');
    state.textContent = game.state === 'post' ? 'Final' : (game.state === 'in' ? game.clock : 'Scheduled');
    const situation = doc.createElement('span');
    situation.textContent = [
      game.possession ? `${game.possession} ball` : '', game.down,
      game.redZone ? 'RED ZONE' : '',
    ].filter(Boolean).join(' · ');
    row.append(matchup, state, situation);
    if (game.lastPlay) {
      const play = doc.createElement('small');
      play.textContent = game.lastPlay;
      row.append(play);
    }
    list.append(row);
  }
  if (!games.length) {
    const empty = doc.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'ESPN returned no games for this preseason week.';
    list.append(empty);
  }
}

function initLiveHarness(doc, win) {
  const root = doc.querySelector('[data-live-harness]');
  if (!root || typeof win.fetch !== 'function') return;
  let request = 0;
  const load = async (week) => {
    const mine = ++request;
    const state = root.querySelector('[data-live-feed-state]');
    if (state) state.textContent = 'Loading…';
    try {
      const season = root.dataset.espnSeason || new Date().getFullYear();
      const url = `${ESPN_SCOREBOARD}?seasontype=1&week=${week}&dates=${season}`;
      const games = await fetchEspnGames(win, url);
      if (mine !== request) return;
      renderLiveHarness(doc, root, games);
      if (state) {
        const live = games.filter((game) => game.state === 'in').length;
        state.textContent = live ? `${live} live · refreshes automatically` : `${games.length} games loaded`;
      }
      const delay = livePollDelay(games);
      if (delay && root.open) win.setTimeout(() => load(week), delay);
    } catch {
      if (mine !== request) return;
      if (state) state.textContent = 'Feed unavailable · try again';
    }
  };
  root.addEventListener('toggle', () => {
    if (!root.open || root.dataset.loaded) return;
    root.dataset.loaded = 'true';
    load(root.querySelector('[data-espn-week][aria-pressed="true"]')?.dataset.espnWeek || '4');
  });
  root.addEventListener('click', (event) => {
    const button = event.target.closest?.('[data-espn-week]');
    if (!button) return;
    for (const other of root.querySelectorAll('[data-espn-week]')) {
      other.setAttribute('aria-pressed', String(other === button));
    }
    load(button.dataset.espnWeek);
  });
}

function initLiveGames(doc, win) {
  if (!doc.querySelector('[data-gameday-card]') || typeof win.fetch !== 'function') return;
  const poll = async () => {
    try {
      const games = await fetchEspnGames(win);
      paintLiveGames(doc, games);
      const delay = livePollDelay(games);
      if (delay) win.setTimeout(poll, delay);
    } catch {
      // Static nflverse state remains visible; an unofficial overlay is never
      // important enough to turn a transient request failure into page noise.
    }
  };
  poll();
}

// ---------------------------------------------------------------------------
// DOM wiring
// ---------------------------------------------------------------------------
function initTheme(doc, storage, win) {
  const button = doc.querySelector('[data-theme-toggle]');
  if (!button) return;

  const root = doc.documentElement;
  button.addEventListener('click', () => {
    const theme = nextTheme(root.dataset.theme);
    const apply = () => {
      root.dataset.theme = theme;
      storage.set(THEME_KEY, theme);
    };

    // The floodlights come on from the switch that turned them on: the new
    // palette is wiped in as a circle growing out of the button. All of it is
    // optional — a browser without View Transitions, or a reader who has asked
    // for less motion, gets the same theme change without the sweep.
    if (!doc.startViewTransition
        || win.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      apply();
      return;
    }

    const box = button.getBoundingClientRect();
    const origin = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
    const size = { width: win.innerWidth, height: win.innerHeight };
    root.style.setProperty('--sweep-x', `${origin.x.toFixed(1)}px`);
    root.style.setProperty('--sweep-y', `${origin.y.toFixed(1)}px`);
    root.style.setProperty('--sweep-r', `${sweepRadius(origin, size).toFixed(1)}px`);

    // The class is what scopes the wipe to this transition. Moving between
    // pages is a view transition too, and that one morphs a row into the hero
    // it becomes — not something to do with a circle.
    root.classList.add('is-relighting');
    const done = () => root.classList.remove('is-relighting');
    // Both arms, not `finally`: a transition that is skipped rejects, and an
    // unhandled rejection in a theme toggle is not worth anyone's console.
    doc.startViewTransition(apply).finished.then(done, done);
  });
}

/**
 * The Details toggle on the standings page.
 *
 * The board's default is the glance: rank, name, teams, points. The outlook
 * bar, the sparkline and the ceiling maths appear for whoever asks, and the
 * choice is remembered per browser. `aria-pressed` tracks the state so the
 * control reads correctly to a screen reader.
 */
function initDetail(doc, storage) {
  const button = doc.querySelector('[data-detail-toggle]');
  if (!button) return;

  const paint = () => {
    button.setAttribute(
      'aria-pressed',
      String(doc.documentElement.dataset.detail === 'on'),
    );
  };
  paint();

  button.addEventListener('click', () => {
    const on = doc.documentElement.dataset.detail === 'on';
    if (on) delete doc.documentElement.dataset.detail;
    else doc.documentElement.dataset.detail = 'on';
    storage.set(DETAIL_KEY, on ? 'off' : 'on');
    paint();
  });
}

/**
 * The schedule's filter: only the games the pool has a side in.
 *
 * A third of any week is games nobody here holds. They are always dimmed and
 * can now be dropped entirely, which is what turns a sixteen-game week into
 * the handful worth reading. One attribute on the root does it — so the rule
 * lives in the stylesheet, costs nothing per row, and survives switching week
 * without anything being re-marked.
 */
function initSlate(doc, storage) {
  const button = doc.querySelector('[data-slate-toggle]');
  if (!button) return;

  const paint = () => {
    button.setAttribute(
      'aria-pressed',
      String(doc.documentElement.dataset.slate === 'pool'),
    );
  };
  paint();

  button.addEventListener('click', () => {
    const on = doc.documentElement.dataset.slate === 'pool';
    if (on) delete doc.documentElement.dataset.slate;
    else doc.documentElement.dataset.slate = 'pool';
    storage.set(SLATE_KEY, on ? 'all' : 'pool');
    paint();
  });
}

/**
 * Opening a game up.
 *
 * Everything in the panel was already in the markup — what each side pays, and
 * to whom, for every entrant rather than only the reader. The button is the
 * control, because a row full of links is not something a keyboard can
 * usefully "press"; clicking the row is a convenience on top of it, and it
 * stands aside whenever the click landed on a link or on the button itself.
 */
function initGameDetail(doc) {
  // One listener per list rather than two per row: the schedule carries 272
  // games, and 544 listeners to open a panel is not a trade worth making. The
  // list rather than the document, because a listener on the document outlives
  // the markup it was about — run this twice over one document and every click
  // would toggle twice and appear to do nothing.
  for (const list of doc.querySelectorAll('.games')) {
    list.addEventListener('click', (event) => {
      const row = event.target.closest?.('.game');
      if (!row) return;

      const button = row.querySelector('[data-game-open]');
      if (!button) return;

      if (!event.target.closest('[data-game-open]')) {
        // A chip, a name — anything that already means something else.
        if (event.target.closest('a, button')) return;
        // And never while the reader is selecting a score to copy it.
        if (doc.defaultView?.getSelection?.()?.toString()) return;
      }

      const open = row.classList.toggle('is-open');
      button.setAttribute('aria-expanded', String(open));
    });
  }
}

/**
 * "This is me": one stored slug that highlights the viewer everywhere.
 *
 * Six near-identical rows on a phone is exactly where finding yourself is the
 * whole job. The choice never leaves the browser — there is no server here to
 * send it to.
 */
/**
 * The viewer's own line, lifted to the top of the standings.
 *
 * Built from the board row that already exists — the strip never adds entrant
 * links of its own, it borrows the row's. Empty (and hidden) until "who are
 * you?" is set, and on every page that has no board.
 */
function paintYouStrip(doc, slug) {
  const strip = doc.querySelector('[data-you]');
  if (!strip) return;

  const row = slug ? doc.querySelector(`.board .row[data-slug="${slug}"]`) : null;
  // The row itself stopped being an anchor when its team chips became links —
  // an anchor inside an anchor is not a thing HTML has. The destination moved
  // one element in, to the name, and the strip still borrows it rather than
  // rebuilding a URL it has no business knowing how to build. No link, no
  // strip: an empty bar above the board says less than nothing.
  const rowLink = row?.querySelector('.row-link');
  strip.textContent = '';
  strip.hidden = !rowLink;
  if (!rowLink) return;

  const grab = (sel) => {
    const el = row.querySelector(sel);
    return el ? el.textContent.trim() : '';
  };

  const link = doc.createElement('a');
  link.href = rowLink.getAttribute('href');

  const rank = doc.createElement('span');
  rank.className = 'you-rank';
  rank.textContent = `#${grab('.row-rank')}`;

  const label = doc.createElement('span');
  label.className = 'you-label';
  label.textContent = 'your entry';

  const name = doc.createElement('span');
  name.textContent = grab('.row-name');

  const pts = doc.createElement('span');
  pts.className = 'you-pts';
  pts.textContent = `${grab('.row-points')} pts`;

  link.append(rank, label, name, pts);
  strip.append(link);
}

function initMe(doc, storage, meKey = ME_KEY) {
  const select = doc.querySelector('[data-me-select]');
  const stored = storage.get(meKey) || '';

  const apply = (slug) => {
    // Absence means nobody is selected. Keeping data-me="" around makes CSS
    // unable to distinguish that state from a real identity, which in turn
    // prevents the ordinary leader highlight from returning when the picker
    // is cleared.
    if (slug) doc.documentElement.dataset.me = slug;
    else delete doc.documentElement.dataset.me;
    for (const el of doc.querySelectorAll('[data-slug]')) {
      el.classList.toggle('is-me', Boolean(slug) && el.dataset.slug === slug);
    }
    paintYouStrip(doc, slug);
  };

  if (select) {
    // A stored name that is no longer in the pool must not leave the picker
    // showing a blank: next season's picks file will not have last year's
    // entrants in it.
    select.value = stored;
    const slug = select.value === stored ? stored : '';
    apply(slug);
    if (slug !== stored) storage.set(meKey, slug);

    select.addEventListener('change', () => {
      storage.set(meKey, select.value);
      apply(select.value);
    });
    return;
  }
  apply(stored);
}

/**
 * The comparison chart: pick who you want to read against.
 *
 * Every line is already in the document; picking only toggles classes and sets
 * a colour, so with scripting off the chart still renders the whole field.
 */
function initCompare(doc, storage, compareKey = COMPARE_KEY) {
  const charts = Array.from(doc.querySelectorAll('[data-compare]'));
  const buttons = Array.from(doc.querySelectorAll('[data-pick]'));
  if (!charts.length || !buttons.length) return;

  const known = new Set(buttons.map((b) => b.dataset.pick));
  const stored = (storage.get(compareKey) || '').split(' ').filter(Boolean);
  const me = doc.documentElement.dataset.me;

  // Nothing stored yet, but they have told us who they are: start on them.
  // Opening the page already showing your own line is the point of the chart.
  let picked = (stored.length ? stored : (me ? [me] : [])).filter((s) => known.has(s));

  const empty = doc.querySelector('[data-compare-empty]');

  const paint = () => {
    const colors = new Map(
      picked.map((slug, i) => [slug, PICK_COLORS[i % PICK_COLORS.length]]),
    );

    for (const button of buttons) {
      const color = colors.get(button.dataset.pick);
      button.setAttribute('aria-pressed', String(Boolean(color)));
      if (color) button.style.setProperty('--pick-color', color);
      else button.style.removeProperty('--pick-color');
    }

    for (const chart of charts) {
      for (const el of chart.querySelectorAll('[data-entrant]')) {
        const color = colors.get(el.dataset.entrant);
        el.classList.toggle('is-picked', Boolean(color));
        if (color) el.style.setProperty('--pick-color', color);
        else el.style.removeProperty('--pick-color');
      }

      // Every label is a link to that entrant's page, but a label nobody has
      // picked is drawn at zero opacity — so the link around it would be a tab
      // stop over nothing at all. It comes back the moment the name does. The
      // pointer is handled in the stylesheet, which already knows how to see
      // an unpicked label.
      for (const link of chart.querySelectorAll('a')) {
        const label = link.querySelector('.cmp-label');
        if (!label) continue;
        link.setAttribute('tabindex', label.classList.contains('is-picked') ? '0' : '-1');
      }

      const labels = Array.from(chart.querySelectorAll('.cmp-label.is-picked'));
      // Bounds from the chart's own viewBox (14 top pad, 26 bottom pad —
      // matching the Python renderer), so an overflowing label stack slides
      // back into view instead of clipping.
      const box = chart.querySelector('svg')?.viewBox?.baseVal;
      const placed = spreadLabels(
        labels.map((el) => ({ slug: el.dataset.entrant, y: Number(el.dataset.y) })),
        14,
        box ? 14 : -Infinity,
        box ? box.height - 26 : Infinity,
      );
      for (const { slug, y } of placed) {
        const el = chart.querySelector(`.cmp-label[data-entrant="${slug}"]`);
        if (el) el.setAttribute('y', String(y + 4));
      }
    }

    if (empty) empty.hidden = picked.length > 0;
    storage.set(compareKey, picked.join(' '));
  };

  for (const button of buttons) {
    button.addEventListener('click', () => {
      const slug = button.dataset.pick;
      picked = picked.includes(slug)
        ? picked.filter((s) => s !== slug)
        // Past the palette, the oldest pick drops out rather than two lines
        // sharing a colour — which would defeat the entire chart.
        : [...picked, slug].slice(-PICK_COLORS.length);
      paint();
    });
  }
  paint();
}

/**
 * Which way a column opens on its first click.
 *
 * The default is the way that column is most useful — biggest first for
 * numbers, A-Z for names — but "biggest first" is wrong for the one kind of
 * number where small is good. A heading can therefore say so outright with
 * `data-sort="ascending"`, and rank columns do.
 */
export function firstSortDirection(th) {
  const declared = th.getAttribute('data-sort');
  if (declared === 'ascending') return 1;
  if (declared === 'descending') return -1;
  return th.classList.contains('num') ? -1 : 1;
}

/** Click (or Enter/Space) a marked column heading to sort the table by it. */
function initSort(doc, win) {
  const still = win.matchMedia('(prefers-reduced-motion: reduce)').matches;

  for (const table of doc.querySelectorAll('table')) {
    const heads = Array.from(table.querySelectorAll('th[data-sort]'));
    if (!heads.length) continue;

    for (const th of heads) {
      th.tabIndex = 0;
      const activate = () => {
        const index = Array.from(th.parentElement.children).indexOf(th);
        // An `aria-sort` already on the heading is the server saying the rows
        // arrived in that order, so the first click reverses it rather than
        // re-sorting to what is already on screen. Otherwise the column opens
        // whichever way it is most useful — see firstSortDirection.
        const current = th.getAttribute('aria-sort');
        const direction = current === null
          ? firstSortDirection(th)
          : (current === 'ascending' ? -1 : 1);

        for (const other of heads) other.removeAttribute('aria-sort');
        th.setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');

        // Read before, sort, then let every row travel from where it was.
        const before = still ? null : rowTops(table);
        sortTable(table, index, direction);
        if (before) glideRows(table, before);
      };

      th.addEventListener('click', activate);
      th.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          activate();
        }
      });
    }
  }
}

function initTimeZone(doc, storage, nowMs) {
  const select = doc.querySelector('[data-tz-select]');
  const stamps = Array.from(doc.querySelectorAll('time[data-ts]'));
  if (!stamps.length) return;

  const stored = storage.get(TZ_KEY);
  let zone = isValidTimeZone(stored) ? stored : DEFAULT_TZ;

  const paint = () => {
    for (const el of stamps) {
      const iso = el.getAttribute('datetime');
      // `data-ts` carries no value on a plain stamp and "kickoff" on a game,
      // and `time[data-ts]` matches both — so this is a pure addition.
      const format = el.dataset.ts === 'kickoff' ? KICKOFF_FORMAT : STAMP_FORMAT;
      if (!iso) continue;
      el.textContent = formatTimestamp(iso, zone, 'en-US', format);

      // The age rides inside the same element, appended after the formatted
      // time, so switching zones rewrites both in one pass and they can never
      // be left disagreeing with each other.
      if (el.dataset.age === undefined) continue;
      const age = relativeAge(iso, nowMs);
      if (age === null) continue;
      const badge = doc.createElement('span');
      badge.className = 'fresh-age';
      badge.classList.toggle('is-stale', isStale(iso, nowMs));
      badge.textContent = age;
      el.append(' ', badge);
    }
  };

  if (select) {
    // A valid stored zone that is not one of the listed options (an old
    // build's list, or a hand-set value) still applies to every timestamp;
    // only the <select> shows blank. The previous code did the opposite of
    // its own comment — it read the emptied select back and snapped the
    // viewer to Eastern.
    select.value = zone;
    select.addEventListener('change', () => {
      zone = select.value;
      storage.set(TZ_KEY, zone);
      paint();
    });
  }
  paint();
}

/**
 * Which week owns `nowMs` — the first one that has not finished yet.
 *
 * The same rule the build ran, against the visitor's clock instead of the
 * build's. Both read the identical baked instants, so the two can only ever
 * disagree about *when* it is, never about what that means.
 *
 * Note this compares absolute instants, so it is independent of the time-zone
 * picker: the games kick off at one moment, and Honolulu and Maine are looking
 * at the same week.
 */
export function weekForInstant(windows, nowMs) {
  const usable = windows.filter((w) => Number.isFinite(w.closesMs));
  if (!usable.length) return null;
  for (const w of usable) {
    if (w.closesMs > nowMs) return w.week;
  }
  // Past the last game of the season, the last week is the thing to show.
  return usable[usable.length - 1].week;
}

function initSchedule(doc, nowMs) {
  const sections = Array.from(doc.querySelectorAll('[data-week][data-closes]'));
  if (!sections.length) return;

  const windows = sections.map((el) => ({
    week: el.dataset.week,
    closesMs: Date.parse(el.dataset.closes),
  }));
  const current = weekForInstant(windows, nowMs);

  // The build's guess is usually right — it is at most a few hours old, and
  // weeks turn over just before midnight on a Monday. This corrects the
  // overnight window between the rollover and the next deploy.
  if (current !== null) {
    for (const el of sections) {
      el.classList.toggle('is-default', el.dataset.week === current);
    }
  }

  const links = Array.from(doc.querySelectorAll('[data-week-link]'));
  for (const link of links) {
    link.classList.toggle('is-now', link.dataset.weekLink === current);
  }

  // Which week you are *looking at*, which is the hash if you followed one and
  // the current week otherwise. Kept in step with the back button.
  const markVisible = () => {
    const shown = doc.location?.hash?.replace('#week-', '') || current;
    for (const link of links) {
      if (link.dataset.weekLink === shown) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
  };
  markVisible();
  doc.defaultView?.addEventListener('hashchange', markVisible);
}

/**
 * The hovered head-to-head cell, written out in full.
 *
 * Two sentences, because one number in isolation is misleading. The pairwise
 * figure says who wins a two-horse race that is not the race being run: "beats
 * him 62% of the time" reads very differently when one of them wins the pool
 * once in three and the other once in fifty. So the claim comes first and what
 * it is worth comes second.
 *
 * The reverse figure is passed in from the opposite cell rather than derived as
 * 100 − p, so the sentence always agrees with the number printed in that cell
 * no matter how either was rounded. Outright odds are optional: without them
 * the claim stands on its own rather than the readout inventing a number.
 *
 * The money grid is the same shape with one difference that matters. Its
 * opposite cells do not add to 100%, because a season that paid neither of
 * them is a season neither out-earned the other — so the remainder is named
 * out loud rather than left as a gap the reader has to notice and explain to
 * themselves. Both figures come from real cells; the ties are what is left.
 */
export function headToHeadReadout({
  row, col, percent, reverse, rowWin, colWin, view = 'order', samePicks = false,
}) {
  // Two entries holding the same four teams cannot separate. The model stores
  // a tie as half a win in each direction so the pairwise matrix still adds to
  // 100%; without this explicit marker that correct internal representation
  // turns into the very misleading sentence "50% above, 50% below".
  if (samePicks) {
    return {
      claim: `${row} and ${col} tie in every simulated season because they have the same picks.`,
      odds: null,
    };
  }

  const other = reverse === undefined || reverse === null
    ? 100 - Number(percent)
    : Number(reverse);

  if (view === 'money') {
    const level = Math.max(100 - Number(percent) - other, 0);
    const claim =
      `${row} takes home more than ${col} in ${percent}% of simulated seasons, `
      + `less in ${other}%`
      + (level > 0 ? `, and the same in the other ${level}%.` : '.');
    if (rowWin == null || colWin == null) return { claim, odds: null };
    return {
      claim,
      odds:
        `Outright, ${row} is paid something ${rowWin}% of the time `
        + `and ${col} ${colWin}%.`,
    };
  }

  const claim =
    `${row} finishes above ${col} in ${percent}% of simulated seasons, `
    + `and below them in the other ${other}%.`;

  if (rowWin == null || colWin == null) return { claim, odds: null };
  return {
    claim,
    odds:
      `Outright, ${row} wins the pool ${rowWin}% of the time `
      + `and ${col} ${colWin}%.`,
  };
}

/**
 * The head-to-head grid: cross-highlight the pair, and say what it means.
 *
 * A square grid of the same names down both axes looks symmetrical and is not,
 * so a bare "62%" leaves the reader to work out whose 62% it is. Lighting up
 * the row and the column, and writing the pair out underneath, answers that
 * without them having to trace two fingers across a chart on a phone.
 *
 * A mouse hovers; a finger cannot. On touch, pointerenter and pointerleave
 * fire in the same instant the tap does, so a highlight wired to hover alone
 * is a flash the reader never sees. Tapping a cell therefore *pins* it — the
 * pair stays lit and the readout stays written until the same cell is tapped
 * again, another cell takes over, the reader taps away, or Escape. A mouse
 * gets the same hold on click, for carrying a pair down to the readout.
 */
function initHeatmap(doc) {
  const readout = doc.querySelector('[data-heat-readout]');
  // The prompt the readout carries when nothing is hovered, restored on exit.
  const rest = readout ? readout.textContent : '';
  // The cell a tap is holding on, or null while the grid is back on hover.
  let pinned = null;

  /** Put every grid on the page back to rest: no glow, prompt restored. */
  const release = () => {
    pinned = null;
    for (const el of doc.querySelectorAll('svg.heat .is-lit, svg.heat .is-picked')) {
      el.classList.remove('is-lit', 'is-picked');
    }
    for (const chart of doc.querySelectorAll('svg.heat.has-pick')) {
      chart.classList.remove('has-pick');
    }
    if (readout) {
      readout.textContent = rest;
      readout.classList.remove('is-live');
    }
  };

  /** Wire one grid up to the readout. Both are live; only one is on screen. */
  const wire = (panel) => {
    const chart = panel.querySelector('svg.heat');
    if (!chart) return;
    const cells = Array.from(chart.querySelectorAll('.heat-box'));
    if (!cells.length) return;
    // Which question this grid is answering. It rides on the panel because the
    // server drew the grid and the server knows; the client is not going to
    // infer it from the numbers.
    const view = panel.dataset?.heatGrid || 'order';

    const mark = (r, c) => {
      for (const el of chart.querySelectorAll('[data-r], [data-c]')) {
        const onAxis = el.dataset.r === r || el.dataset.c === c;
        const exact = el.dataset.r === r && el.dataset.c === c;
        el.classList.toggle('is-lit', onAxis);
        el.classList.toggle('is-picked', exact);
      }
    };

    /** Outright odds live on the axis label, so there are 2n, not n². */
    const winOdds = (axis, index) =>
      chart.querySelector(`.heat-${axis}[data-${axis[0]}="${index}"]`)?.dataset.win ?? null;

    // The two names in this sentence stay plain, and deliberately: the readout
    // is written on pointer-enter and wiped on pointer-leave, so a link in it
    // could never be reached — moving towards it is what erases it. Both
    // people are one row up, on the axes of the grid this sentence is about,
    // where they are links like everywhere else.
    const say = (cell) => {
      if (!readout) return;
      const { r, c } = cell.dataset;
      const opposite = chart.querySelector(`.heat-box[data-r="${c}"][data-c="${r}"]`);
      const parts = headToHeadReadout({
        row: cell.dataset.row,
        col: cell.dataset.col,
        percent: cell.dataset.p,
        reverse: opposite?.dataset.p,
        rowWin: winOdds('row', r),
        colWin: winOdds('col', c),
        view,
        samePicks: cell.dataset.samePicks === 'true',
      });

      readout.textContent = '';
      // The stylesheet promotes a live readout on a phone, where it doubles
      // as the tooltip a hover would have been.
      readout.classList.add('is-live');
      const claim = doc.createElement('span');
      claim.className = 'heat-claim';
      claim.textContent = parts.claim;
      readout.append(claim);
      if (!parts.odds) return;
      const odds = doc.createElement('span');
      odds.className = 'heat-odds';
      odds.textContent = parts.odds;
      readout.append(odds);
    };

    const show = (cell) => {
      mark(cell.dataset.r, cell.dataset.c);
      say(cell);
    };

    for (const cell of cells) {
      cell.addEventListener('pointerenter', () => {
        // While a tap holds a pair, a pointer passing over the grid must not
        // steal it — the reader is mid-sentence in the readout.
        if (!pinned) show(cell);
      });
      cell.addEventListener('click', () => {
        if (pinned === cell) {
          release();
          return;
        }
        release();
        pinned = cell;
        // The class carries what :hover carries for a mouse — everything off
        // the picked pair steps back — because a finger has no hover.
        chart.classList.add('has-pick');
        show(cell);
      });
    }
    chart.addEventListener('pointerleave', () => {
      if (!pinned) release();
    });
  };

  // A page with one unwrapped grid — which is every page but the forecast —
  // still gets the readout wiring, so this stays one code path.
  const panels = Array.from(doc.querySelectorAll('[data-heat-grid]'));
  if (panels.length) panels.forEach(wire);
  else if (doc.querySelector('svg.heat')) wire(doc);

  if (panels.length || doc.querySelector('svg.heat')) {
    // Tapping anywhere that is not the grid lets a pinned pair go — the same
    // gesture that dismisses everything else on a phone. A click on a cell
    // never lands here with a pin still held: the cell's own handler has
    // already re-pinned or released by the time the click bubbles this far.
    doc.addEventListener('click', (e) => {
      if (pinned && !e.target?.closest?.('svg.heat')) release();
    });
    doc.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && pinned) release();
    });
  }

  initHeatView(doc, release);
}

/**
 * The picker over the two grids: who finishes above whom, or who out-earns whom.
 *
 * Both grids are in the document already, drawn by the same code from the same
 * simulations, so choosing between them is `hidden` and nothing else — no
 * arithmetic on the client, and no way for the two to disagree. The note above
 * the grid is swapped with it, because the money grid's opposite cells add to
 * less than 100% and a reader is owed the reason on the same screen as the
 * evidence.
 */
function initHeatView(doc, release) {
  const select = doc.querySelector('[data-heat-view]');
  if (!select) return;

  const grids = Array.from(doc.querySelectorAll('[data-heat-grid]'));
  const notes = Array.from(doc.querySelectorAll('[data-heat-note]'));
  if (!grids.length) return;

  const show = (view) => {
    for (const grid of grids) grid.hidden = grid.dataset.heatGrid !== view;
    for (const note of notes) note.hidden = note.dataset.heatNote !== view;
    // The readout is describing a cell in the grid that just left the screen,
    // and a pinned pair belongs to it too — let the whole state go together.
    release();
  };

  // Whatever the markup shipped as visible is the truth at load; the select is
  // pulled into line with it rather than the other way round, so a browser
  // restoring a stale selection cannot leave the page showing one grid and
  // naming the other.
  const shown = grids.find((grid) => !grid.hidden);
  if (shown) select.value = shown.dataset.heatGrid;
  select.addEventListener('change', () => show(select.value));
}

/**
 * Tracing a team through the playoffs.
 *
 * Point at (or tab to) any team in the bracket and every game on its road to
 * the trophy comes forward while the rest of the field steps back — the same
 * move a March bracket makes when you follow one line through it. All of it
 * is classes: the stylesheet owns what "forward" looks like, and with no
 * script the bracket is simply all there, which is the honest failure mode
 * for a static page.
 */
function initBracket(doc) {
  const bracket = doc.querySelector('[data-bracket]');
  if (!bracket) return;
  // Before anything is seeded every side is an empty slot, and there is
  // nothing to trace — the listeners would only ever clear.
  const sides = Array.from(bracket.querySelectorAll('.tie-side[data-team]'));
  if (!sides.length) return;
  const ties = Array.from(bracket.querySelectorAll('.tie'));

  const trace = (team) => {
    bracket.classList.toggle('is-tracing', Boolean(team));
    for (const side of sides) {
      side.classList.toggle('is-path', Boolean(team) && side.dataset.team === team);
    }
    // A tie is on the path if either of its sides is — highlighting the whole
    // game rather than half a card, because the game is the unit that pays.
    for (const tie of ties) {
      tie.classList.toggle('has-path', Boolean(team) && Boolean(tie.querySelector('.is-path')));
    }
  };

  const teamOf = (target) =>
    target && target.closest
      ? target.closest('.tie-side[data-team]')?.dataset.team ?? null
      : null;

  // Delegated, so thirteen games cost two listeners rather than fifty-two.
  // Pointing anywhere that is not a team — a slot, a label, the gap — clears,
  // which is what makes the trace feel attached to the pointer.
  const retrace = (event) => trace(teamOf(event.target));
  bracket.addEventListener('mouseover', retrace);
  bracket.addEventListener('mouseleave', () => trace(null));
  bracket.addEventListener('focusin', retrace);
  bracket.addEventListener('focusout', (event) => {
    if (!teamOf(event.relatedTarget)) trace(null);
  });
}

/**
 * The definition popovers.
 *
 * Hover and focus open one; a tap toggles it, which is the case that rules out
 * a pure-CSS `:hover` tooltip — on a touch screen the first tap would both
 * open the tooltip and follow through to whatever was underneath it. Only one
 * is ever open, because two overlapping definitions explain nothing.
 */
function initGlossary(doc, win) {
  const terms = Array.from(doc.querySelectorAll('.term'));
  if (!terms.length) return;

  let open = null;

  const close = () => {
    if (!open) return;
    open.classList.remove('is-open');
    open.querySelector('.info')?.setAttribute('aria-expanded', 'false');
    open = null;
  };

  const show = (term) => {
    if (open === term) return;
    close();
    const button = term.querySelector('.info');
    const def = term.querySelector('.def');
    if (!button || !def) return;

    // Made visible before measuring: a hidden element reports a zero-height
    // box, and the tooltip would then be placed as though it were a sliver.
    term.classList.add('is-open');
    button.setAttribute('aria-expanded', 'true');
    open = term;

    const box = def.getBoundingClientRect();
    const spot = tooltipPosition(
      button.getBoundingClientRect(),
      { width: box.width, height: box.height },
      { width: win.innerWidth, height: win.innerHeight },
    );
    def.style.left = `${spot.left}px`;
    def.style.top = `${spot.top}px`;
  };

  for (const term of terms) {
    const button = term.querySelector('.info');
    if (!button) continue;

    term.addEventListener('pointerenter', () => show(term));
    term.addEventListener('pointerleave', () => {
      // A tap leaves the pointer nowhere, and closing on that would undo the
      // tap that opened it. Only a mouse leaving actually means "done here".
      if (!term.contains(doc.activeElement)) close();
    });
    button.addEventListener('focus', () => show(term));
    button.addEventListener('blur', close);
    button.addEventListener('click', (event) => {
      event.preventDefault();
      // Several of these sit inside a sortable column heading, and that
      // heading sorts on click. Asking what a column means must not also
      // reorder the table under the reader.
      event.stopPropagation();
      if (open === term) close();
      else show(term);
    });
    button.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') event.stopPropagation();
    });
  }

  doc.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close();
  });
  // Anything that moves the page moves the anchor out from under the popover.
  win.addEventListener('scroll', close, { passive: true });
  win.addEventListener('resize', close);
}

/**
 * Paint the field, and repaint it when the viewport or the theme changes.
 *
 * Deliberately not repainted on scroll: the field is anchored to the viewport,
 * so scrolling does not move it, and the only thing that travels is the
 * first-down line — which is its own element and its own transform.
 */
function initGridiron(doc, win) {
  const canvas = doc.querySelector('canvas.gridiron');
  // No 2D context is the honest answer on a document that is being read
  // rather than rendered — a headless parser, a feed reader, a test. The
  // stylesheet's turf is already on the page, so there is nothing to do and
  // nothing to report. Wrapped because "not implemented" is a thrown error in
  // some environments and a null return in others.
  let ctx = null;
  try {
    ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
  } catch {
    ctx = null;
  }
  if (!ctx) return;

  const marks = { near: canvas.dataset.near, far: canvas.dataset.far };
  let painted = { width: 0, height: 0 };

  const paint = () => {
    const width = win.innerWidth;
    const height = win.innerHeight;
    const ratio = Math.min(win.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    drawField(
      ctx,
      fieldGeometry(width, height),
      fieldPalette(win.getComputedStyle(doc.documentElement)),
      marks,
    );
    painted = { width, height };
  };

  paint();

  // A phone hides and shows its address bar constantly, and each of those is a
  // resize event for a viewport nobody actually changed. Width always counts;
  // height has to move further than the browser chrome before it does.
  win.addEventListener('resize', () => {
    const grew = Math.abs(win.innerHeight - painted.height) > 120;
    if (win.innerWidth !== painted.width || grew) paint();
  });

  // The theme toggle rewrites one attribute; every colour on the field hangs
  // off it, so that attribute is what the field watches.
  if (win.MutationObserver) {
    new win.MutationObserver(paint).observe(doc.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
  }

  // Web fonts land after first paint, and the yard numbers are set in the
  // display face. Without this they are drawn in the fallback and stay there.
  doc.fonts?.ready?.then(paint).catch(() => {});
}

/**
 * The chain crew, moving downfield as the page scrolls.
 *
 * Reading the scroll position inside the animation frame rather than inside
 * the scroll event is the whole trick: the handler does nothing but ask for a
 * frame, so a fast flick queues one repaint instead of forty.
 *
 * Everything else here is a class. Which yard the marks are on is a transform,
 * and what they look like when they get there — ordinary, inside the twenty,
 * over the line — belongs to the stylesheet.
 */
function initDrive(doc, win) {
  if (win.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const drive = doc.querySelector('.drive');
  const line = doc.querySelector('.drive-line');
  const yard = doc.querySelector('.drive-yard');
  if (!drive || !line) return;

  let queued = false;

  const place = () => {
    queued = false;
    const height = win.innerHeight;
    const scrollMax = (doc.documentElement.scrollHeight || 0) - height;
    const progress = scrollProgress(win.scrollY || 0, scrollMax);

    // Goal line to goal line: the hundred yards of playing field, never the
    // end zones, because the line of scrimmage cannot be inside one.
    const spot = progress * 100;
    const geom = fieldGeometry(win.innerWidth, height);
    line.style.transform = `translate3d(0, ${yardToY(geom, END_ZONE_YARDS + spot).toFixed(1)}px, 0)`;
    if (yard) yard.textContent = driveLabel(spot);
    // A page with nowhere to scroll would otherwise park a bright mark across
    // the top of it and call that a feature.
    drive.classList.toggle('is-live', scrollMax > height * 0.35);
    // The yard label waits until the drive has actually left the goal line. At
    // the top of the page the mark sits under the masthead, which puts the
    // label in the viewer bar and cuts it in half.
    drive.classList.toggle('is-moving', progress > 0.02);
    drive.classList.toggle('is-redzone', spot >= RED_ZONE);
    // Only at the very bottom, and only once per arrival — toggle leaves the
    // class alone while it is already there, so the flare does not restart on
    // every frame of a rubber-band scroll.
    drive.classList.toggle('is-td', progress >= 1);
  };

  const request = () => {
    if (queued) return;
    queued = true;
    win.requestAnimationFrame(place);
  };

  place();
  win.addEventListener('scroll', request, { passive: true });
  win.addEventListener('resize', request);
}

function initOdometer(doc, win) {
  if (win.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const targets = Array.from(doc.querySelectorAll('.row-points, .hero-total'));
  const runs = targets
    .map((el) => ({ el, value: Number.parseFloat(el.textContent) }))
    .filter((t) => Number.isFinite(t.value) && t.value > 0);
  if (!runs.length) return;

  const duration = 620;
  const start = win.performance.now();
  const settle = () => {
    for (const { el, value } of runs) el.textContent = value.toFixed(2);
  };

  // If animation frames stop arriving — a backgrounded tab, a throttled
  // device — the count-up must not strand a half-counted number on screen.
  // This guarantees the true value regardless of what the frames do.
  win.setTimeout(settle, duration + 400);

  const step = (now) => {
    const progress = (now - start) / duration;
    if (progress >= 1) {
      settle();
      return;
    }
    for (const { el, value } of runs) {
      el.textContent = countUpValue(value, progress).toFixed(2);
    }
    win.requestAnimationFrame(step);
  };
  win.requestAnimationFrame(step);
}

/**
 * Blocks that arrive as you reach them.
 *
 * The hidden state is applied here rather than in the stylesheet, and that is
 * the whole reason this is safe: with scripting off nothing is ever hidden, so
 * a failed observer cannot cost anyone the page. The class is removed for good
 * once an element has been seen — this is an entrance, not a parallax.
 */
/**
 * Blocks, and only blocks — the panels, cards and rows that read as objects.
 *
 * Headings and body copy are deliberately not in here. Animating a section
 * title while the paragraph underneath it is already on the page makes the
 * section look like it is assembling itself out of order; the titles are what
 * you scan for, and they should simply be there.
 */
export const REVEAL_SELECTOR = [
  '.state-cell',
  '.stat',
  '.card',
  '.chart-card',
  '.table-scroll',
  '.forecast-row',
  '.heat-wrap',
  '.tie',
].join(', ');

function initReveal(doc, win) {
  if (win.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (!win.IntersectionObserver) return;

  const main = doc.querySelector('main');
  if (!main) return;

  const observer = new win.IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.remove('will-reveal');
        observer.unobserve(entry.target);
      }
    },
    // A margin off the bottom, so a block has finished arriving by the time
    // it is somewhere you would actually be looking at it.
    { rootMargin: '0px 0px -8% 0px', threshold: 0.01 },
  );

  for (const el of main.querySelectorAll(REVEAL_SELECTOR)) {
    // Anything not currently rendered is left alone. The schedule shows one
    // week and hides the rest in CSS, and hiding those blocks a second time
    // would mean a week you switch to is briefly, or on a throttled observer
    // permanently, blank. Nothing here is worth that.
    if (el.checkVisibility && !el.checkVisibility()) continue;
    // Nor is anything already on screen. This module is deferred, so on a slow
    // connection the first screen can be painted before it runs — hiding what
    // the reader is already looking at would be a flicker, and there is no
    // entrance to play for something that has already arrived.
    const box = el.getBoundingClientRect();
    if ((box.width || box.height) && box.top < win.innerHeight) continue;
    el.classList.add('will-reveal');
    observer.observe(el);
  }
}

export function init(doc = document, win = window) {
  const storage = safeStorage(win.localStorage);
  // Which pool this page belongs to — '' at the site root. Only the two keys
  // that name entrants are scoped by it; see scopedKey.
  const scope = doc.documentElement.dataset.pool || '';
  initTheme(doc, storage, win);
  initDetail(doc, storage);
  initSlate(doc, storage);
  initGameDetail(doc);
  // Identity first: the comparison chart opens on whoever the viewer says
  // they are, so it has to know before it paints.
  initMe(doc, storage, scopedKey(ME_KEY, scope));
  paintGamedayOrder(doc, win);
  doc.querySelector('[data-me-select]')?.addEventListener(
    'change', () => paintGamedayOrder(doc, win),
  );
  // The clock comes in through `win` so a test can stand anywhere in the season
  // without touching global time — the same discipline the Python side follows
  // by passing the fetch instant around rather than calling now().
  const nowMs = (win.Date ?? Date).now();
  initTimeZone(doc, storage, nowMs);
  initSchedule(doc, nowMs);
  initScenario(doc, win);
  initLiveGames(doc, win);
  initLiveHarness(doc, win);
  initCompare(doc, storage, scopedKey(COMPARE_KEY, scope));
  initSort(doc, win);
  initOdometer(doc, win);
  initHeatmap(doc);
  initBracket(doc);
  initGlossary(doc, win);
  initGridiron(doc, win);
  initDrive(doc, win);
  initReveal(doc, win);
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init());
  } else {
    init();
  }
}
