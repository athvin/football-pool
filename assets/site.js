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
export const COMPARE_KEY = 'pool-compare';
export const DEFAULT_TZ = 'America/New_York';
export const DEFAULT_THEME = 'dark';

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
  const key = `${locale}|${timeZone}|${format.weekday ?? ''}`;
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
export function spreadLabels(items, gap = 14) {
  let previous = -Infinity;
  return [...items]
    .sort((a, b) => a.y - b.y)
    .map(({ slug, y }) => {
      const placed = Math.max(y, previous + gap);
      previous = placed;
      return { slug, y: placed };
    });
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
 * "This is me": one stored slug that highlights the viewer everywhere.
 *
 * Six near-identical rows on a phone is exactly where finding yourself is the
 * whole job. The choice never leaves the browser — there is no server here to
 * send it to.
 */
function initMe(doc, storage) {
  const select = doc.querySelector('[data-me-select]');
  const stored = storage.get(ME_KEY) || '';

  const apply = (slug) => {
    doc.documentElement.dataset.me = slug;
    for (const el of doc.querySelectorAll('[data-slug]')) {
      el.classList.toggle('is-me', Boolean(slug) && el.dataset.slug === slug);
    }
  };

  if (select) {
    // A stored name that is no longer in the pool must not leave the picker
    // showing a blank: next season's picks file will not have last year's
    // entrants in it.
    select.value = stored;
    const slug = select.value === stored ? stored : '';
    apply(slug);
    if (slug !== stored) storage.set(ME_KEY, slug);

    select.addEventListener('change', () => {
      storage.set(ME_KEY, select.value);
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
function initCompare(doc, storage) {
  const charts = Array.from(doc.querySelectorAll('[data-compare]'));
  const buttons = Array.from(doc.querySelectorAll('[data-pick]'));
  if (!charts.length || !buttons.length) return;

  const known = new Set(buttons.map((b) => b.dataset.pick));
  const stored = (storage.get(COMPARE_KEY) || '').split(' ').filter(Boolean);
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
      const placed = spreadLabels(
        labels.map((el) => ({ slug: el.dataset.entrant, y: Number(el.dataset.y) })),
      );
      for (const { slug, y } of placed) {
        const el = chart.querySelector(`.cmp-label[data-entrant="${slug}"]`);
        if (el) el.setAttribute('y', String(y + 4));
      }
    }

    if (empty) empty.hidden = picked.length > 0;
    storage.set(COMPARE_KEY, picked.join(' '));
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

/** Click (or Enter/Space) a marked column heading to sort the table by it. */
function initSort(doc) {
  for (const table of doc.querySelectorAll('table')) {
    const heads = Array.from(table.querySelectorAll('th[data-sort]'));
    if (!heads.length) continue;

    for (const th of heads) {
      th.tabIndex = 0;
      const activate = () => {
        const index = Array.from(th.parentElement.children).indexOf(th);
        // First click on a column sorts the way that column is most useful:
        // biggest-first for numbers, A-Z for names.
        const wasAscending = th.getAttribute('aria-sort') === 'ascending';
        const direction = wasAscending ? -1 : 1;

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

function initTimeZone(doc, storage) {
  const select = doc.querySelector('[data-tz-select]');
  const stamps = Array.from(doc.querySelectorAll('time[data-ts]'));
  if (!stamps.length) return;

  const stored = storage.get(TZ_KEY);
  let zone = isValidTimeZone(stored) ? stored : DEFAULT_TZ;

  const paint = () => {
    for (const el of stamps) {
      const iso = el.getAttribute('datetime');
      // `data-ts` carries no value on a footer stamp and "kickoff" on a game,
      // and `time[data-ts]` matches both — so this is a pure addition.
      const format = el.dataset.ts === 'kickoff' ? KICKOFF_FORMAT : STAMP_FORMAT;
      if (iso) el.textContent = formatTimestamp(iso, zone, 'en-US', format);
    }
  };

  if (select) {
    select.value = zone;
    // A zone we do not list (someone's stored value, or a future edit) should
    // still apply rather than silently snapping back to Eastern.
    if (select.value !== zone) zone = select.value || DEFAULT_TZ;
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

export function init(doc = document, win = window) {
  const storage = safeStorage(win.localStorage);
  initTheme(doc, storage);
  // Identity first: the comparison chart opens on whoever the viewer says
  // they are, so it has to know before it paints.
  initMe(doc, storage);
  initTimeZone(doc, storage);
  // The clock comes in through `win` so a test can stand anywhere in the season
  // without touching global time — the same discipline the Python side follows
  // by passing the fetch instant around rather than calling now().
  initSchedule(doc, (win.Date ?? Date).now());
  initCompare(doc, storage);
  initSort(doc);
  initOdometer(doc, win);
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init());
  } else {
    init();
  }
}
