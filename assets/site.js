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
// DOM wiring
// ---------------------------------------------------------------------------
function initTheme(doc, storage) {
  const button = doc.querySelector('[data-theme-toggle]');
  if (!button) return;
  button.addEventListener('click', () => {
    const theme = nextTheme(doc.documentElement.dataset.theme);
    doc.documentElement.dataset.theme = theme;
    storage.set(THEME_KEY, theme);
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
  strip.textContent = '';
  strip.hidden = !row;
  if (!row) return;

  const grab = (sel) => {
    const el = row.querySelector(sel);
    return el ? el.textContent.trim() : '';
  };

  const link = doc.createElement('a');
  link.href = row.getAttribute('href');

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
    doc.documentElement.dataset.me = slug;
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
function initSort(doc) {
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
        sortTable(table, index, direction);
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

/** The hovered head-to-head cell, written out as an English sentence. */
export function headToHeadSentence(row, col, percent) {
  return `${row} finishes above ${col} in ${percent}% of simulated seasons.`;
}

/**
 * The head-to-head grid: cross-highlight the pair, and say what it means.
 *
 * A square grid of the same names down both axes looks symmetrical and is not,
 * so a bare "62%" leaves the reader to work out whose 62% it is. Lighting up
 * the row and the column, and writing the pair out underneath, answers that
 * without them having to trace two fingers across a chart on a phone.
 */
function initHeatmap(doc) {
  const chart = doc.querySelector('svg.heat');
  const readout = doc.querySelector('[data-heat-readout]');
  if (!chart) return;

  const cells = Array.from(chart.querySelectorAll('.heat-box'));
  if (!cells.length) return;
  // The prompt the readout carries when nothing is hovered, restored on exit.
  const rest = readout ? readout.textContent : '';

  const mark = (r, c) => {
    for (const el of chart.querySelectorAll('[data-r], [data-c]')) {
      const onAxis = el.dataset.r === r || el.dataset.c === c;
      const exact = el.dataset.r === r && el.dataset.c === c;
      el.classList.toggle('is-lit', onAxis);
      el.classList.toggle('is-picked', exact);
    }
  };

  const clear = () => {
    for (const el of chart.querySelectorAll('.is-lit, .is-picked')) {
      el.classList.remove('is-lit', 'is-picked');
    }
    if (readout) readout.textContent = rest;
  };

  for (const cell of cells) {
    cell.addEventListener('pointerenter', () => {
      mark(cell.dataset.r, cell.dataset.c);
      if (readout) {
        readout.textContent = headToHeadSentence(
          cell.dataset.row, cell.dataset.col, cell.dataset.p,
        );
      }
    });
  }
  chart.addEventListener('pointerleave', clear);
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
 * The first-down line, driving downfield as the page scrolls.
 *
 * Reading the scroll position inside the animation frame rather than inside
 * the scroll event is the whole trick: the handler does nothing but ask for a
 * frame, so a fast flick queues one repaint instead of forty.
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
    // A page with nowhere to scroll would otherwise park a bright line across
    // the top of it and call that a feature.
    drive.classList.toggle('is-live', scrollMax > height * 0.35);
    // The yard chip waits until the drive has actually left the goal line. At
    // the top of the page the line sits under the masthead, which puts the
    // chip in the viewer bar and cuts the label in half.
    drive.classList.toggle('is-moving', progress > 0.02);
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
  initTheme(doc, storage);
  initDetail(doc, storage);
  // Identity first: the comparison chart opens on whoever the viewer says
  // they are, so it has to know before it paints.
  initMe(doc, storage, scopedKey(ME_KEY, scope));
  // The clock comes in through `win` so a test can stand anywhere in the season
  // without touching global time — the same discipline the Python side follows
  // by passing the fetch instant around rather than calling now().
  const nowMs = (win.Date ?? Date).now();
  initTimeZone(doc, storage, nowMs);
  initSchedule(doc, nowMs);
  initCompare(doc, storage, scopedKey(COMPARE_KEY, scope));
  initSort(doc);
  initOdometer(doc, win);
  initHeatmap(doc);
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
