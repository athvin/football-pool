/**
 * Tests for the site's client-side behaviour.
 *
 * The pure helpers are tested directly; `init()` is exercised against a jsdom
 * document that mirrors the real markup, so the wiring is covered too.
 */

import { beforeEach, describe, expect, test, vi } from 'vitest';

import {
  DEFAULT_TZ,
  THEME_KEY,
  TZ_KEY,
  countUpValue,
  easeOutCubic,
  formatTimestamp,
  init,
  isValidTimeZone,
  nextTheme,
  safeStorage,
} from '../../assets/site.js';

const ISO = '2026-02-09T14:30:00+00:00';

describe('nextTheme', () => {
  test('flips an explicit theme', () => {
    expect(nextTheme('dark', false)).toBe('light');
    expect(nextTheme('light', false)).toBe('dark');
  });

  test('resolves "no preference" against the operating system', () => {
    // No stored choice: the first click should move away from what they see.
    expect(nextTheme(undefined, true)).toBe('light');
    expect(nextTheme(undefined, false)).toBe('dark');
    expect(nextTheme('', true)).toBe('light');
  });
});

describe('formatTimestamp', () => {
  test('renders a UTC instant in the requested zone', () => {
    const eastern = formatTimestamp(ISO, 'America/New_York');
    expect(eastern).toContain('9:30');
    expect(eastern).toContain('EST');
  });

  test('the same instant differs by zone', () => {
    const eastern = formatTimestamp(ISO, 'America/New_York');
    const pacific = formatTimestamp(ISO, 'America/Los_Angeles');
    expect(eastern).not.toBe(pacific);
    expect(pacific).toContain('6:30');
  });

  test('falls back to the raw string rather than blanking the stamp', () => {
    expect(formatTimestamp('not-a-date', 'UTC')).toBe('not-a-date');
    expect(formatTimestamp(ISO, 'Mars/Olympus')).toBe(ISO);
  });
});

describe('isValidTimeZone', () => {
  test.each([
    ['America/New_York', true],
    ['UTC', true],
    ['Mars/Olympus', false],
    ['', false],
    [null, false],
    [undefined, false],
  ])('%s -> %s', (tz, expected) => {
    expect(isValidTimeZone(tz)).toBe(expected);
  });
});

describe('count-up maths', () => {
  test('easing is clamped and monotonic', () => {
    expect(easeOutCubic(-1)).toBe(0);
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(2)).toBe(1);
    expect(easeOutCubic(0.25)).toBeLessThan(easeOutCubic(0.75));
  });

  test('the count-up starts at zero and lands exactly on the target', () => {
    expect(countUpValue(42.5, 0)).toBe(0);
    expect(countUpValue(42.5, 1)).toBeCloseTo(42.5, 10);
    expect(countUpValue(42.5, 0.5)).toBeGreaterThan(0);
    expect(countUpValue(42.5, 0.5)).toBeLessThan(42.5);
  });
});

describe('safeStorage', () => {
  test('reads and writes through to the underlying store', () => {
    const store = new Map();
    const s = safeStorage({
      getItem: (k) => store.get(k) ?? null,
      setItem: (k, v) => store.set(k, v),
    });
    s.set('a', '1');
    expect(s.get('a')).toBe('1');
    expect(s.get('missing')).toBeNull();
  });

  test('swallows errors when storage is unavailable', () => {
    // Private browsing throws on both read and write.
    const s = safeStorage({
      getItem() { throw new Error('denied'); },
      setItem() { throw new Error('denied'); },
    });
    expect(s.get('a')).toBeNull();
    expect(() => s.set('a', '1')).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// DOM wiring
// ---------------------------------------------------------------------------
function markup() {
  document.documentElement.removeAttribute('data-theme');
  document.body.innerHTML = `
    <button data-theme-toggle></button>
    <span class="row-points">39.20</span>
    <span class="hero-total">39.20</span>
    <time datetime="${ISO}" data-ts>${ISO}</time>
    <select data-tz-select>
      <option value="America/New_York">Eastern</option>
      <option value="America/Chicago">Central</option>
      <option value="UTC">UTC</option>
    </select>`;
}

function fakeWindow({ reduceMotion = false, prefersDark = true, store = new Map() } = {}) {
  const frames = [];
  return {
    localStorage: {
      getItem: (k) => store.get(k) ?? null,
      setItem: (k, v) => store.set(k, v),
    },
    matchMedia: (query) => ({
      matches: query.includes('reduced-motion') ? reduceMotion : prefersDark,
    }),
    performance: { now: () => 0 },
    requestAnimationFrame: (fn) => frames.push(fn),
    setTimeout: (fn) => fn(),
    _frames: frames,
    _store: store,
  };
}

describe('init', () => {
  beforeEach(markup);

  test('the toggle switches the theme and remembers it', () => {
    const win = fakeWindow({ prefersDark: true });
    init(document, win);

    document.querySelector('[data-theme-toggle]').click();
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(win._store.get(THEME_KEY)).toBe('light');

    document.querySelector('[data-theme-toggle]').click();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  test('timestamps localise to Eastern by default', () => {
    init(document, fakeWindow());
    const text = document.querySelector('time[data-ts]').textContent;
    expect(text).toContain('EST');
    expect(text).not.toBe(ISO);
    expect(document.querySelector('[data-tz-select]').value).toBe(DEFAULT_TZ);
  });

  test('changing the zone repaints every stamp and stores the choice', () => {
    const win = fakeWindow();
    init(document, win);

    const select = document.querySelector('[data-tz-select]');
    select.value = 'UTC';
    select.dispatchEvent(new window.Event('change'));

    expect(document.querySelector('time[data-ts]').textContent).toContain('UTC');
    expect(win._store.get(TZ_KEY)).toBe('UTC');
  });

  test('a stored zone is restored on the next visit', () => {
    const store = new Map([[TZ_KEY, 'America/Chicago']]);
    init(document, fakeWindow({ store }));
    expect(document.querySelector('[data-tz-select]').value).toBe('America/Chicago');
    expect(document.querySelector('time[data-ts]').textContent).toContain('CST');
  });

  test('a corrupt stored zone falls back to Eastern', () => {
    const store = new Map([[TZ_KEY, 'Mars/Olympus']]);
    init(document, fakeWindow({ store }));
    expect(document.querySelector('[data-tz-select]').value).toBe(DEFAULT_TZ);
  });

  test('the odometer settles on the true value', () => {
    const win = fakeWindow();
    init(document, win);
    // The safety timeout fires synchronously in the fake window, so the real
    // number is on screen even if no animation frame ever runs.
    expect(document.querySelector('.row-points').textContent).toBe('39.20');
    expect(document.querySelector('.hero-total').textContent).toBe('39.20');
  });

  test('animation frames converge on the true value', () => {
    const win = fakeWindow();
    win.setTimeout = () => {}; // disable the safety net to test the frames
    let clock = 0;
    win.performance.now = () => clock;
    init(document, win);

    // Run the queued frames forward past the animation duration.
    for (let i = 0; i < 5 && win._frames.length; i += 1) {
      clock += 400;
      win._frames.shift()(clock);
    }
    expect(document.querySelector('.row-points').textContent).toBe('39.20');
  });

  test('reduced motion skips the count-up entirely', () => {
    const win = fakeWindow({ reduceMotion: true });
    init(document, win);
    expect(win._frames).toHaveLength(0);
    expect(document.querySelector('.row-points').textContent).toBe('39.20');
  });

  test('pages with no stamps or toggle do not throw', () => {
    document.body.innerHTML = '<p>nothing to wire up</p>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });

  test('stamps still localise without a picker', () => {
    document.body.innerHTML = `<time datetime="${ISO}" data-ts>${ISO}</time>`;
    init(document, fakeWindow());
    expect(document.querySelector('time[data-ts]').textContent).toContain('EST');
  });

  test('a stamp with no datetime attribute is left alone', () => {
    document.body.innerHTML = '<time data-ts>whenever</time>';
    init(document, fakeWindow());
    expect(document.querySelector('time[data-ts]').textContent).toBe('whenever');
  });

  test('non-numeric score text is not animated', () => {
    document.body.innerHTML = '<span class="row-points">—</span>';
    const win = fakeWindow();
    init(document, win);
    expect(document.querySelector('.row-points').textContent).toBe('—');
    expect(win._frames).toHaveLength(0);
  });
});
