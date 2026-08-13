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
export const DEFAULT_TZ = 'America/New_York';

/** Flip between themes, resolving "no stored preference" against the OS. */
export function nextTheme(current, prefersDark) {
  if (current === 'dark') return 'light';
  if (current === 'light') return 'dark';
  return prefersDark ? 'light' : 'dark';
}

/**
 * Render a UTC timestamp in the viewer's chosen zone.
 *
 * Falls back to the original string rather than throwing, because a bad stored
 * time zone should never blank out the "data through" stamp.
 */
export function formatTimestamp(iso, timeZone, locale = 'en-US') {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat(locale, {
      timeZone,
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    }).format(when);
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
function initTheme(doc, storage, media) {
  const button = doc.querySelector('[data-theme-toggle]');
  if (!button) return;
  button.addEventListener('click', () => {
    const theme = nextTheme(doc.documentElement.dataset.theme, media.matches);
    doc.documentElement.dataset.theme = theme;
    storage.set(THEME_KEY, theme);
  });
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
      if (iso) el.textContent = formatTimestamp(iso, zone);
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
  initTheme(doc, storage, win.matchMedia('(prefers-color-scheme: dark)'));
  initTimeZone(doc, storage);
  initOdometer(doc, win);
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init());
  } else {
    init();
  }
}
