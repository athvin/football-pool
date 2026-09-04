/**
 * Tests for the site's client-side behaviour.
 *
 * The pure helpers are tested directly; `init()` is exercised against a jsdom
 * document that mirrors the real markup, so the wiring is covered too.
 */

import { beforeEach, describe, expect, test, vi } from 'vitest';

import {
  COMPARE_KEY,
  DEFAULT_THEME,
  DEFAULT_TZ,
  END_ZONE_YARDS,
  FIELD_YARDS,
  ME_KEY,
  scopedKey,
  PICK_COLORS,
  RED_ZONE,
  REVEAL_SELECTOR,
  ESPN_SCOREBOARD,
  LIVE_POLL_MS,
  PREGAME_POLL_MS,
  STALE_AFTER_HOURS,
  THEME_KEY,
  TZ_KEY,
  cellValue,
  centeredScrollLeft,
  compareValues,
  countUpValue,
  drawField,
  driveLabel,
  dreamScenario,
  easeOutCubic,
  fieldGeometry,
  fieldPalette,
  firstSortDirection,
  flipShifts,
  formatTimestamp,
  gamedayLaunchParams,
  headToHeadReadout,
  init,
  isStale,
  isValidTimeZone,
  markerNumber,
  nextTheme,
  normalizeEspnTeam,
  outsideHelpGames,
  outsideHelpScenario,
  outsideHelpTeams,
  parseEspnScoreboard,
  parseScenarioHash,
  preseasonScoreboardUrl,
  relativeAge,
  rowTops,
  safeStorage,
  scenarioLocation,
  scenarioPreset,
  scenarioStandings,
  scrollProgress,
  serializeScenario,
  sortTable,
  spreadLabels,
  sweepRadius,
  tooltipPosition,
  weekForInstant,
  livePollDelay,
  yardToY,
} from '../../assets/site.js';

const ISO = '2026-02-09T14:30:00+00:00';

// documentElement survives between tests in jsdom, and data-pool namespaces the
// stored identity for every block that calls init(). Cleared centrally rather
// than in each markup helper so a block that opts into a pool cannot silently
// leave the next one there — which is exactly how it broke the first time.
beforeEach(() => {
  document.documentElement.removeAttribute('data-pool');
  document.documentElement.removeAttribute('data-page');
  document.documentElement.style.removeProperty('--masthead-height');
  document.documentElement.style.removeProperty('--viewer-height');
});

describe('nextTheme', () => {
  test('flips an explicit theme', () => {
    expect(nextTheme('dark')).toBe('light');
    expect(nextTheme('light')).toBe('dark');
  });

  test('dark is the default, so anything unset flips to light', () => {
    // The site does not follow the operating system: dark is the default
    // unconditionally, so the first click always lands on light no matter
    // what the viewer's OS is set to.
    expect(DEFAULT_THEME).toBe('dark');
    expect(nextTheme(undefined)).toBe('light');
    expect(nextTheme('')).toBe('light');
    expect(nextTheme('nonsense')).toBe('light');
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

describe('horizontal navigation placement', () => {
  test('centres an item when there is room on both sides', () => {
    expect(centeredScrollLeft(300, 80, 240, 700)).toBe(220);
  });

  test('clamps the first and last items to the rail edges', () => {
    expect(centeredScrollLeft(10, 80, 240, 700)).toBe(0);
    expect(centeredScrollLeft(650, 50, 240, 700)).toBe(460);
  });

  test('a rail that already fits does not move', () => {
    expect(centeredScrollLeft(50, 80, 300, 280)).toBe(0);
    expect(centeredScrollLeft(Number.NaN, 80, 240, 700)).toBe(0);
  });
});

describe('spreadLabels', () => {
  test('leaves labels that already clear each other alone', () => {
    const out = spreadLabels([{ slug: 'a', y: 10 }, { slug: 'b', y: 90 }], 14);
    expect(out).toEqual([{ slug: 'a', y: 10 }, { slug: 'b', y: 90 }]);
  });

  test('pushes a collision apart by exactly the gap', () => {
    const out = spreadLabels([{ slug: 'a', y: 50 }, { slug: 'b', y: 50 }], 14);
    expect(out).toEqual([{ slug: 'a', y: 50 }, { slug: 'b', y: 64 }]);
  });

  test('a whole stack on one value fans out in order', () => {
    const out = spreadLabels(
      [{ slug: 'a', y: 20 }, { slug: 'b', y: 22 }, { slug: 'c', y: 24 }],
      14,
    );
    expect(out.map((o) => o.y)).toEqual([20, 34, 48]);
  });

  test('output is sorted top to bottom regardless of input order', () => {
    const out = spreadLabels([{ slug: 'z', y: 80 }, { slug: 'a', y: 10 }], 14);
    expect(out.map((o) => o.slug)).toEqual(['a', 'z']);
  });

  test('does not mutate the input', () => {
    const input = [{ slug: 'a', y: 50 }, { slug: 'b', y: 50 }];
    spreadLabels(input, 14);
    expect(input.map((i) => i.y)).toEqual([50, 50]);
  });

  test('an empty set is fine', () => {
    expect(spreadLabels([], 14)).toEqual([]);
  });

  test('an overflowing stack slides back up into the plot', () => {
    // 90/95/100 with a 14px gap fan to 90/104/118; a 110px floor slides the
    // run up by 8 so the last label stays inside the viewBox instead of
    // clipping — the correction the Python renderer always had.
    const out = spreadLabels(
      [{ slug: 'a', y: 90 }, { slug: 'b', y: 95 }, { slug: 'c', y: 100 }],
      14, 10, 110,
    );
    expect(out.map((o) => o.y)).toEqual([82, 96, 110]);
  });
});

describe('table sorting', () => {
  test('numbers sort numerically, not as text', () => {
    // The bug this guards: "10" < "9" lexically, so a points column sorted as
    // text puts double digits in the wrong place the moment week 5 arrives.
    expect(compareValues('9', '10')).toBeLessThan(0);
    expect(compareValues('2.60', '1.45')).toBeGreaterThan(0);
    expect(compareValues('5', '5')).toBe(0);
  });

  test('non-numeric values fall back to text rather than being read as zero', () => {
    // "0-0" must not parse as 0 and silently tie with a real zero.
    expect(compareValues('3-1', '10-2')).toBeLessThan(0);
    expect(compareValues('Brian', 'Paul')).toBeLessThan(0);
  });

  test('an empty cell is not treated as zero', () => {
    expect(compareValues('', '5')).toBeLessThan(0);
    expect(compareValues('5', '')).toBeGreaterThan(0);
  });

  test('cellValue prefers an explicit sort key over the displayed text', () => {
    document.body.innerHTML =
      '<table><tbody><tr><td data-value="7">seven</td><td>plain</td></tr></tbody></table>';
    const row = document.querySelector('tr');
    expect(cellValue(row, 0)).toBe('7');
    expect(cellValue(row, 1)).toBe('plain');
    expect(cellValue(row, 9)).toBe('');
  });

  test('sortTable reorders the body in place', () => {
    document.body.innerHTML = `
      <table><tbody>
        <tr><td>b</td><td data-value="2">2</td></tr>
        <tr><td>a</td><td data-value="30">30</td></tr>
        <tr><td>c</td><td data-value="9">9</td></tr>
      </tbody></table>`;
    const table = document.querySelector('table');

    sortTable(table, 1, 1);
    expect([...table.tBodies[0].rows].map((r) => r.cells[1].textContent)).toEqual(
      ['2', '9', '30'],
    );

    sortTable(table, 1, -1);
    expect([...table.tBodies[0].rows].map((r) => r.cells[1].textContent)).toEqual(
      ['30', '9', '2'],
    );

    sortTable(table, 0, 1);
    expect([...table.tBodies[0].rows].map((r) => r.cells[0].textContent)).toEqual(
      ['a', 'b', 'c'],
    );
  });

  test('a table with no body is a no-op rather than a crash', () => {
    document.body.innerHTML = '<table><thead><tr><th>x</th></tr></thead></table>';
    expect(sortTable(document.querySelector('table'), 0, 1)).toEqual([]);
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

describe('Gameday scenario helpers', () => {
  const data = {
    entrants: [
      { slug: 'a', name: 'Alex', teams: ['SEA', 'BUF'], banked: 10 },
      { slug: 'b', name: 'Blair', teams: ['KC', 'MIA'], banked: 12 },
      { slug: 'c', name: 'Casey', teams: [], banked: 12 },
    ],
    games: [
      {
        id: '2026_01_KC_SEA', away: 'KC', home: 'SEA', tie: true,
        favorite: 'KC', chaos: 'SEA',
        points: {
          a: { KC: 0, SEA: 5, TIE: 2.5 },
          b: { KC: 4, SEA: 0, TIE: 2 },
          c: { KC: 0, SEA: 0, TIE: 0 },
        },
      },
      {
        id: '2026_02_BUF_MIA', away: 'BUF', home: 'MIA', tie: false,
        favorite: 'MIA', chaos: 'BUF',
        points: { a: { BUF: 1, MIA: 0 }, b: { BUF: 0, MIA: 3 }, c: { BUF: 0, MIA: 0 } },
      },
    ],
  };

  test('fragment round-trips valid calls and ignores stale or illegal ones', () => {
    const selected = { '2026_01_KC_SEA': 'TIE', '2026_02_BUF_MIA': 'BUF' };
    const hash = serializeScenario(selected, data.games);
    expect(hash).toBe('#scenario=2026_01_KC_SEA:TIE,2026_02_BUF_MIA:BUF');
    expect(parseScenarioHash(hash, data.games)).toEqual(selected);
    expect(parseScenarioHash('#scenario=old%3AKC%2C2026_02_BUF_MIA%3ATIE', data.games)).toEqual({});
    expect(parseScenarioHash('#something-else', data.games)).toEqual({});
    expect(parseScenarioHash('#scenario=%E0%A4%A', data.games)).toEqual({});
  });

  test('entrant links carry identity into one initial preset and keep it shareable', () => {
    expect(gamedayLaunchParams('?me=julie&preset=dream')).toEqual({
      me: 'julie', preset: 'dream',
    });
    expect(gamedayLaunchParams('?me=julie&preset=unknown')).toEqual({
      me: 'julie', preset: '',
    });
    expect(scenarioLocation(
      '/football-pool/gameday/',
      '?me=julie&preset=dream&utm_source=entrant',
      '#scenario=g%3AJAX',
    )).toBe('/football-pool/gameday/?me=julie&utm_source=entrant#scenario=g%3AJAX');
  });

  test('called points recalculate totals with competition ranks', () => {
    const standings = scenarioStandings(data, { '2026_01_KC_SEA': 'SEA' });
    expect(standings.map((row) => [row.slug, row.total, row.rank])).toEqual([
      ['a', 15, 1], ['b', 12, 2], ['c', 12, 2],
    ]);
  });

  test('presets call chalk, upsets, a selected dream, or nothing', () => {
    expect(scenarioPreset(data, 'likely')).toEqual({
      '2026_01_KC_SEA': 'KC', '2026_02_BUF_MIA': 'MIA',
    });
    expect(scenarioPreset(data, 'chaos')).toEqual({
      '2026_01_KC_SEA': 'SEA', '2026_02_BUF_MIA': 'BUF',
    });
    expect(scenarioPreset(data, 'dream', 'a')).toEqual({
      '2026_01_KC_SEA': 'SEA', '2026_02_BUF_MIA': 'BUF',
    });
    expect(scenarioPreset(data, 'help', 'a')).toEqual({
      '2026_01_KC_SEA': 'SEA', '2026_02_BUF_MIA': 'BUF',
    });
    expect(scenarioPreset(data, 'dream')).toEqual({});
    expect(scenarioPreset(data, 'reset')).toEqual({});
  });

  test('a dream optimizes the whole board and can never demote a chalk leader', () => {
    const trap = {
      entrants: [
        { slug: 'brian', name: 'Brian', banked: 10 },
        { slug: 'rival', name: 'Rival', banked: 9.5 },
        { slug: 'third', name: 'Third', banked: 0 },
      ],
      games: [{
        id: 'trap', away: 'SAFE', home: 'SHINY', favorite: 'SAFE', chaos: 'SHINY',
        points: {
          brian: { SAFE: 0, SHINY: 5 },
          rival: { SAFE: 0, SHINY: 6 },
          third: { SAFE: 0, SHINY: 0 },
        },
      }],
    };

    // SHINY gives Brian the larger isolated gain, but gives the rival even
    // more and costs first. Whole-board optimization keeps the safe call.
    expect(dreamScenario(trap, 'brian')).toEqual({ trap: 'SAFE' });
    expect(scenarioStandings(trap, scenarioPreset(trap, 'dream', 'brian'))
      .find((entrant) => entrant.slug === 'brian').rank).toBe(1);
    expect(dreamScenario(trap, '')).toEqual({});
  });

  test('outside help forces my side, then names only consequential other winners', () => {
    const help = {
      entrants: [
        { slug: 'me', name: 'Me', teams: ['MINE'], banked: 10 },
        { slug: 'rival', name: 'Rival', teams: ['FOE', 'THREAT'], banked: 10 },
      ],
      games: [
        {
          id: 'mine', away: 'MINE', home: 'FOE', favorite: 'FOE',
          points: { me: { MINE: 2, FOE: 0 }, rival: { MINE: 0, FOE: 8 } },
        },
        {
          id: 'help', away: 'HELPER', home: 'THREAT', favorite: 'THREAT',
          points: { me: { HELPER: 0, THREAT: 0 }, rival: { HELPER: 0, THREAT: 4 } },
        },
        {
          id: 'noise', away: 'A', home: 'B', favorite: 'A',
          points: { me: { A: 0, B: 0 }, rival: { A: 0, B: 0 } },
        },
      ],
    };

    const selections = outsideHelpScenario(help, 'me');
    expect(selections).toEqual({ mine: 'MINE', help: 'HELPER', noise: 'A' });
    expect(outsideHelpGames(help, selections, 'me')).toEqual([{ id: 'help', team: 'HELPER' }]);
    expect(outsideHelpTeams(help, selections, 'me')).toEqual(['HELPER']);
    expect(outsideHelpScenario(help, '')).toEqual({});
  });

  test('oversized malformed slates fail calm instead of locking the browser', () => {
    const games = Array.from({ length: 17 }, (_, i) => ({
      id: `g${i}`, away: 'A', home: 'H', favorite: 'A', points: { a: { A: 0, H: 1 } },
    }));
    expect(Object.values(dreamScenario({ entrants: [{ slug: 'a', banked: 0 }], games }, 'a')))
      .toEqual(Array(17).fill('A'));
  });
});

describe('ESPN live scoreboard adapter', () => {
  const payload = {
    events: [{
      id: 401,
      date: '2026-08-21T23:00:00Z',
      season: { type: 1 },
      week: { number: 3 },
      status: { period: 3, displayClock: '4:12', type: { state: 'in', shortDetail: '4:12 - 3rd' } },
      competitions: [{
        competitors: [
          { id: '1', homeAway: 'away', score: '17', winner: false, team: { abbreviation: 'WSH' } },
          { id: '2', homeAway: 'home', score: '20', winner: true, team: { abbreviation: 'JAC' } },
        ],
        venue: { fullName: 'Test Field' },
        broadcasts: [{ names: ['ESPN'] }],
        situation: {
          possession: '1', downDistanceText: '3rd & 7 at JAX 42', isRedZone: true,
          lastPlay: { text: 'Pass complete for 12 yards.' },
        },
      }],
    }],
  };

  test('normalizes team codes and extracts the live situation', () => {
    expect(ESPN_SCOREBOARD).toContain('site.web.api.espn.com');
    expect(normalizeEspnTeam('LA')).toBe('LAR');
    expect(normalizeEspnTeam('BUF')).toBe('BUF');
    expect(parseEspnScoreboard({ events: [{ competitions: [] }] })).toEqual([]);
    const [game] = parseEspnScoreboard(payload);
    expect(game).toMatchObject({
      away: 'WAS', home: 'JAX', awayScore: '17', homeScore: '20',
      state: 'in', clock: 'Q3 4:12', possession: 'WAS', redZone: true,
      down: '3rd & 7 at JAX 42', lastPlay: 'Pass complete for 12 yards.', week: 3,
      date: '2026-08-21T23:00:00Z', status: '4:12 - 3rd', venue: 'Test Field',
      network: 'ESPN', homeWinner: true, awayWinner: false,
      seasonType: 1,
    });
    expect(preseasonScoreboardUrl(2026)).toContain('dates=20260715-20260915');
  });

  test('polls by game state instead of hammering a quiet feed', () => {
    expect(livePollDelay([{ state: 'in' }])).toBe(LIVE_POLL_MS);
    expect(livePollDelay([{ state: 'pre' }])).toBe(PREGAME_POLL_MS);
    expect(livePollDelay([{ state: 'post' }])).toBe(0);
  });
});

describe('Gameday DOM wiring', () => {
  const postPayload = {
    events: [{
      id: 900,
      status: { period: 4, displayClock: '0:00', type: { state: 'post' } },
      competitions: [{
        competitors: [
          { id: '1', homeAway: 'away', score: '24', team: { abbreviation: 'KC' } },
          { id: '2', homeAway: 'home', score: '21', team: { abbreviation: 'SEA' } },
        ],
      }],
    }],
  };
  const response = (payload = postPayload, status = 200) => ({
    ok: status < 400, status, json: async () => payload,
  });
  const settle = async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  };

  test('an ESPN final updates a static matchup without a rebuild', async () => {
    document.body.innerHTML = `
      <article data-gameday-card="g" data-away="KC" data-home="SEA" data-drama="10">
        <div data-live-game hidden><b data-live-status></b><span data-live-score></span><span data-live-situation></span></div>
        <div data-live-detail hidden><p data-live-last-play></p></div>
      </article>`;
    const win = fakeWindow();
    win.fetch = vi.fn(async () => response());
    init(document, win);
    await settle();

    expect(win.fetch).toHaveBeenCalledOnce();
    expect(document.querySelector('[data-live-game]').hidden).toBe(false);
    expect(document.querySelector('[data-live-status]').textContent).toBe('Final');
    expect(document.querySelector('[data-live-score]').textContent).toContain('KC 24');
  });

  test('a 403 on the browser host retries the legacy host', async () => {
    document.body.innerHTML = `
      <article data-gameday-card="g" data-away="KC" data-home="SEA">
        <div data-live-game hidden><b data-live-status></b><span data-live-score></span><span data-live-situation></span></div>
      </article>`;
    const win = fakeWindow();
    win.fetch = vi.fn()
      .mockResolvedValueOnce(response({}, 403))
      .mockResolvedValueOnce(response());
    init(document, win);
    await settle();

    expect(win.fetch).toHaveBeenCalledTimes(2);
    expect(win.fetch.mock.calls[0][0]).toContain('site.web.api.espn.com');
    expect(win.fetch.mock.calls[1][0]).toContain('site.api.espn.com');
  });

  test('an opaque fetch rejection can still try the alternate host', async () => {
    document.body.innerHTML = `
      <article data-gameday-card="g" data-away="KC" data-home="SEA">
        <div data-live-game hidden><b data-live-status></b><span data-live-score></span><span data-live-situation></span></div>
      </article>`;
    const win = fakeWindow();
    win.fetch = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(response());
    init(document, win);
    await settle();

    expect(win.fetch).toHaveBeenCalledTimes(2);
    expect(document.querySelector('[data-live-status]').textContent).toBe('Final');
  });

  test('the deployed preseason bench loads a chosen week on demand', async () => {
    document.body.innerHTML = `
      <details data-live-harness data-espn-season="2026" data-team-base="/football-pool/team/">
        <summary><span data-live-feed-state></span></summary>
        <button data-espn-week="3">Preseason Week 2</button>
        <button data-espn-week="4" aria-pressed="true">Preseason Week 3</button>
        <div data-live-team-chips hidden>
          <span data-live-team="KC"><a class="team-chip is-large scored" href="/football-pool/team/KC/" style="--team-bg:#e31837"><img class="chip-logo chip-logo-lg" src="/football-pool/assets/logos/KC.png" alt="">KC</a></span>
          <span data-live-team="SEA"><a class="team-chip is-large scored" href="/football-pool/team/SEA/" style="--team-bg:#002244"><img class="chip-logo chip-logo-lg" src="/football-pool/assets/logos/SEA.png" alt="">SEA</a></span>
        </div>
        <div data-live-harness-games></div>
      </details>`;
    const win = fakeWindow();
    win.fetch = vi.fn(async () => response());
    init(document, win);
    const bench = document.querySelector('[data-live-harness]');
    bench.open = true;
    bench.dispatchEvent(new Event('toggle'));
    await settle();

    expect(win.fetch.mock.calls[0][0]).toContain('seasontype=1&week=4&dates=2026');
    expect(document.querySelector('.live-lab-game').textContent).toContain('KC 24');
    expect(document.querySelector('[data-live-feed-state]').textContent)
      .toBe('Preseason Week 3 · 1 game loaded');
    const chips = Array.from(document.querySelectorAll('.live-lab-matchup .team-chip'));
    expect(chips.map((chip) => chip.getAttribute('href'))).toEqual([
      '/football-pool/team/KC/', '/football-pool/team/SEA/',
    ]);
    expect(chips.every((chip) => chip.querySelector('.chip-logo'))).toBe(true);

    document.querySelector('[data-espn-week="3"]').click();
    await settle();
    expect(win.fetch.mock.calls[1][0]).toContain('week=3');
    expect(document.querySelector('[data-live-feed-state]').textContent)
      .toBe('Preseason Week 2 · 1 game loaded');
  });

  test('scenario controls repaint totals, share exact picks, and build identity-aware dream calls', async () => {
    const data = {
      entrants: [
        { slug: 'a', name: 'Alex', teams: ['SEA'], banked: 10 },
        { slug: 'b', name: 'Blair', teams: ['KC', 'MIA'], banked: 12 },
      ],
      games: [
        {
          id: 'g', away: 'KC', home: 'SEA', tie: true, favorite: 'KC', chaos: 'SEA',
          points: { a: { KC: 0, SEA: 5, TIE: 2 }, b: { KC: 4, SEA: 0, TIE: 2 } },
        },
        {
          id: 'h', away: 'BUF', home: 'MIA', tie: false, favorite: 'MIA', chaos: 'BUF',
          points: { a: { BUF: 0, MIA: 0 }, b: { BUF: 0, MIA: 4 } },
        },
      ],
    };
    document.body.innerHTML = `
      <select data-me-select><option value=""></option><option value="a">Alex</option><option value="b">Blair</option></select>
      <section data-scenario>
        <button data-scenario-preset="likely">Likely</button>
        <button data-scenario-preset="chaos">Chaos</button>
        <button data-scenario-preset="dream">Dream</button>
        <button data-scenario-preset="help">Help</button>
        <button data-scenario-preset="reset">Reset</button>
        <fieldset data-scenario-game="g"><button data-scenario-choice="SEA">SEA</button>
          <details data-scenario-drilldown><summary>Matchup details</summary>
            <strong data-scenario-call></strong><span data-scenario-impact></span>
            <a data-scenario-team="KC" href="/team/KC/#game-g">KC</a>
            <a data-scenario-team="SEA" href="/team/SEA/#game-g">SEA</a>
          </details>
        </fieldset>
        <fieldset data-scenario-game="h"><button data-scenario-choice="BUF">BUF</button>
          <button data-scenario-choice="MIA">MIA</button>
        </fieldset>
        <ol data-scenario-board>
          <li data-slug="a"><i class="scenario-rank"></i><span class="scenario-total"></span></li>
          <li data-slug="b"><i class="scenario-rank"></i><span class="scenario-total"></span></li>
        </ol>
        <button data-scenario-share></button><p data-scenario-status></p>
      </section>
      <script id="gameday-data" type="application/json">${JSON.stringify(data)}</script>`;
    const win = fakeWindow();
    win.location = { href: 'https://example.test/football-pool/gameday/#scenario=SEA' };
    win.navigator = { clipboard: { writeText: vi.fn(async () => {}) } };
    init(document, win);

    expect(document.querySelector('[data-scenario-preset="reset"]').getAttribute('aria-pressed'))
      .toBe('true');
    document.querySelector('[data-scenario-preset="dream"]').click();
    expect(document.querySelector('[data-scenario-status]').textContent).toContain('Choose who');
    const select = document.querySelector('[data-me-select]');
    select.value = 'a';
    select.dispatchEvent(new Event('change'));
    document.querySelector('[data-scenario-preset="dream"]').click();
    expect(document.querySelector('li[data-slug="a"] .scenario-total').textContent).toBe('15.00');
    expect(document.querySelector('li[data-slug="a"] .scenario-rank').textContent).toBe('1');
    expect(document.querySelector('[data-scenario-choice="SEA"]').getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelector('[data-scenario-drilldown]').open).toBe(false);
    expect(document.querySelector('[data-scenario-call]').textContent).toBe('SEA over KC');
    expect(document.querySelector('[data-scenario-impact]').textContent).toContain('Alex +5.00');
    expect(document.querySelector('[data-scenario-team="SEA"]').classList.contains('is-called')).toBe(true);
    expect(document.querySelector('[data-scenario-status]').textContent).toContain("Alex's best slate lands at #1");
    expect(document.querySelector('[data-scenario-preset="dream"]').getAttribute('aria-pressed'))
      .toBe('true');
    select.value = 'b';
    select.dispatchEvent(new Event('change'));
    expect(document.querySelector('[data-scenario-status]').textContent)
      .toContain("Blair's best slate lands at #1");
    expect(document.querySelector('[data-scenario-preset="dream"]').getAttribute('aria-pressed'))
      .toBe('true');
    select.value = 'a';
    select.dispatchEvent(new Event('change'));
    document.querySelector('[data-scenario-choice="SEA"]').click();
    expect(document.querySelector('[data-scenario-drilldown]').open).toBe(true);
    expect(document.querySelectorAll('[data-scenario-preset][aria-pressed="true"]'))
      .toHaveLength(0);
    document.querySelector('[data-scenario-preset="reset"]').click();
    expect(document.querySelector('li[data-slug="a"] .scenario-total').textContent).toBe('10.00');
    expect(document.querySelector('[data-scenario-impact]').textContent).toContain('Choose a result');
    expect(document.querySelector('[data-scenario-preset="reset"]').getAttribute('aria-pressed'))
      .toBe('true');
    document.querySelector('[data-scenario-preset="likely"]').click();
    expect(document.querySelector('[data-scenario-preset="likely"]').getAttribute('aria-pressed'))
      .toBe('true');
    document.querySelector('[data-scenario-preset="chaos"]').click();
    expect(document.querySelector('[data-scenario-preset="chaos"]').getAttribute('aria-pressed'))
      .toBe('true');
    document.querySelector('[data-scenario-preset="help"]').click();
    expect(document.querySelector('[data-scenario-choice="SEA"]').getAttribute('aria-pressed'))
      .toBe('true');
    expect(document.querySelector('[data-scenario-choice="BUF"]').getAttribute('aria-pressed'))
      .toBe('true');
    expect(document.querySelector('[data-scenario-choice="BUF"]').classList.contains('is-outside-help'))
      .toBe(true);
    expect(document.querySelector('[data-scenario-choice="SEA"]').classList.contains('is-outside-help'))
      .toBe(false);
    expect(document.querySelector('[data-scenario-status]').textContent)
      .toContain('root for BUF in the other games');
    expect(document.querySelector('[data-scenario-preset="help"]').getAttribute('aria-pressed'))
      .toBe('true');
    document.querySelector('[data-scenario-preset="reset"]').click();
    document.querySelector('[data-scenario-share]').click();
    await settle();
    expect(win.navigator.clipboard.writeText)
      .toHaveBeenCalledWith('https://example.test/football-pool/gameday/#scenario=SEA');
    expect(document.querySelector('[data-scenario-status]').textContent)
      .toContain('paste it into a text or group chat');
  });

  test('the rooting-board button shows only consequential teams outside my picks', () => {
    const data = {
      entrants: [
        { slug: 'me', name: 'Alex', teams: ['MINE'], banked: 10 },
        { slug: 'rival', name: 'Blair', teams: ['FOE', 'THREAT'], banked: 10 },
      ],
      games: [
        {
          id: 'mine', away: 'MINE', home: 'FOE', favorite: 'FOE',
          points: { me: { MINE: 2, FOE: 0 }, rival: { MINE: 0, FOE: 8 } },
        },
        {
          id: 'help', away: 'HELPER', home: 'THREAT', favorite: 'THREAT',
          points: { me: { HELPER: 0, THREAT: 0 }, rival: { HELPER: 0, THREAT: 4 } },
        },
        {
          id: 'noise', away: 'A', home: 'B', favorite: 'A',
          points: { me: { A: 0, B: 0 }, rival: { A: 0, B: 0 } },
        },
      ],
    };
    const card = (id, away, home) => `
      <article data-gameday-card="${id}" data-away="${away}" data-home="${home}">
        <div class="gameday-side" data-team="${away}"></div>
        <div class="gameday-side" data-team="${home}"></div>
      </article>`;
    document.body.innerHTML = `
      <select data-me-select><option value=""></option><option value="me">Alex</option></select>
      <button data-rooting-help aria-pressed="false"><span data-rooting-help-label>Outside help only</span></button>
      <p data-rooting-help-status></p>
      <div data-gameday-cards>
        ${card('mine', 'MINE', 'FOE')}
        ${card('help', 'HELPER', 'THREAT')}
        ${card('noise', 'A', 'B')}
      </div>
      <p data-rooting-help-empty hidden></p>
      <script id="gameday-data" type="application/json">${JSON.stringify(data)}</script>`;
    const win = fakeWindow();
    init(document, win);
    const button = document.querySelector('[data-rooting-help]');

    button.click();
    expect(button.getAttribute('aria-pressed')).toBe('false');
    expect(document.querySelector('[data-rooting-help-status]').textContent).toContain('Choose who');

    const select = document.querySelector('[data-me-select]');
    select.value = 'me';
    select.dispatchEvent(new Event('change'));
    button.click();

    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelector('[data-rooting-help-label]').textContent).toBe('Show all games');
    expect(document.querySelector('[data-gameday-cards]').classList.contains('is-help-filtered')).toBe(true);
    expect(document.querySelector('[data-gameday-card="help"]').classList.contains('is-help-game')).toBe(true);
    expect(document.querySelector('[data-gameday-card="mine"]').classList.contains('is-help-game')).toBe(false);
    expect(document.querySelector('[data-gameday-card="noise"]').classList.contains('is-help-game')).toBe(false);
    expect(document.querySelector('[data-team="HELPER"]').classList.contains('is-needed')).toBe(true);
    expect(document.querySelector('[data-rooting-help-status]').textContent)
      .toBe("Assuming Alex's teams win, root for HELPER in the games below.");

    button.click();
    expect(button.getAttribute('aria-pressed')).toBe('false');
    expect(document.querySelector('[data-rooting-help-label]').textContent).toBe('Outside help only');
    expect(document.querySelectorAll('.is-help-game, .is-needed')).toHaveLength(0);
  });

  test('an entrant Gameday link selects them and opens on their best slate', () => {
    const data = {
      entrants: [
        { slug: 'julie', name: 'Julie', teams: ['JAX'], banked: 10 },
        { slug: 'rival', name: 'Rival', teams: ['TEN'], banked: 12 },
      ],
      games: [{
        id: 'g', away: 'JAX', home: 'TEN', favorite: 'TEN', chaos: 'JAX',
        points: { julie: { JAX: 5, TEN: 0 }, rival: { JAX: 0, TEN: 4 } },
      }],
    };
    document.documentElement.dataset.page = 'gameday';
    document.body.innerHTML = `
      <select data-me-select><option value=""></option><option value="julie">Julie</option><option value="rival">Rival</option></select>
      <section data-scenario>
        <button data-scenario-preset="dream">Dream</button>
        <button data-scenario-preset="reset">Reset</button>
        <fieldset data-scenario-game="g">
          <button data-scenario-choice="JAX">JAX</button>
          <button data-scenario-choice="TEN">TEN</button>
        </fieldset>
        <ol data-scenario-board>
          <li data-slug="julie"><i class="scenario-rank"></i><span class="scenario-total"></span></li>
          <li data-slug="rival"><i class="scenario-rank"></i><span class="scenario-total"></span></li>
        </ol>
        <p data-scenario-status></p>
      </section>
      <script id="gameday-data" type="application/json">${JSON.stringify(data)}</script>`;
    const store = new Map();
    const win = fakeWindow({ store });
    win.location = {
      pathname: '/football-pool/gameday/',
      search: '?me=julie&preset=dream',
      hash: '',
    };
    win.history = { replaceState: vi.fn() };
    init(document, win);

    expect(document.documentElement.dataset.me).toBe('julie');
    expect(document.querySelector('[data-me-select]').value).toBe('julie');
    expect(document.querySelector('[data-slug="julie"]').classList.contains('is-me')).toBe(true);
    expect(store.get(ME_KEY)).toBe('julie');
    expect(document.querySelector('[data-scenario-preset="dream"]').getAttribute('aria-pressed'))
      .toBe('true');
    expect(document.querySelector('[data-scenario-choice="JAX"]').getAttribute('aria-pressed'))
      .toBe('true');
    expect(document.querySelector('[data-scenario-status]').textContent)
      .toContain("Julie's best slate lands at #1");
    expect(win.history.replaceState.mock.calls.at(-1)[2])
      .toBe('/football-pool/gameday/?me=julie#scenario=g:JAX');
  });

  test('the Schedule PRE tab lazily renders scores, venue, network, and team links', async () => {
    document.body.innerHTML = `
      <select data-tz-select><option value="America/New_York">Eastern</option></select>
      <a href="#preseason">PRE</a>
      <section data-preseason-schedule data-espn-season="2026" data-team-base="/football-pool/team/">
        <span data-preseason-state></span>
        <button data-preseason-week="all">All</button>
        <button data-preseason-week="3" aria-pressed="true">Week 2</button>
        <div data-preseason-team-chips hidden>
          <span data-preseason-team="KC"><a class="team-chip is-large scored" href="/football-pool/team/KC/" style="--team-bg:#e31837"><img class="chip-logo chip-logo-lg" src="/football-pool/assets/logos/KC.png" alt="">KC</a></span>
          <span data-preseason-team="SEA"><a class="team-chip is-large scored" href="/football-pool/team/SEA/" style="--team-bg:#002244"><img class="chip-logo chip-logo-lg" src="/football-pool/assets/logos/SEA.png" alt="">SEA</a></span>
        </div>
        <p data-preseason-summary></p><div data-preseason-games></div>
      </section>`;
    const win = fakeWindow();
    const finished = structuredClone(postPayload);
    finished.events[0].date = '2026-08-21T23:00:00Z';
    finished.events[0].season = { type: 1 };
    finished.events[0].week = { number: 3 };
    finished.events[0].status.type.shortDetail = 'Final';
    finished.events[0].competitions[0].venue = { fullName: 'Test Field' };
    finished.events[0].competitions[0].broadcasts = [{ names: ['ESPN'] }];
    finished.events[0].competitions[0].competitors[1].winner = true;
    win.fetch = vi.fn(async () => response(finished));
    init(document, win);
    expect(win.fetch).not.toHaveBeenCalled();

    const preseasonLink = document.querySelector('a[href="#preseason"]');
    preseasonLink.addEventListener('click', (event) => event.preventDefault());
    preseasonLink.click();
    await settle();

    expect(win.fetch).toHaveBeenCalledOnce();
    expect(win.fetch.mock.calls[0][0]).toContain('seasontype=1');
    expect(win.fetch.mock.calls[0][0]).toContain('limit=1000');
    expect(document.querySelector('[data-preseason-state]').textContent).toContain('1 games loaded');
    expect(document.querySelector('.preseason-game').textContent).toContain('KC');
    expect(document.querySelector('.preseason-game').textContent).toContain('Test Field · ESPN');
    expect(document.querySelector('.preseason-side.is-winner .team-chip').href)
      .toContain('/football-pool/team/SEA/');
    expect(document.querySelector('.preseason-side .chip-logo').src)
      .toContain('/football-pool/assets/logos/KC.png');
    expect(document.querySelector('[data-preseason-summary]').textContent).toContain('1 game · 1 final');
  });

  test('stored identity ordering settles once without replaying the interaction animation', () => {
    document.body.innerHTML = `
      <select data-me-select><option value=""></option><option value="a">Alex</option></select>
      <div data-gameday-cards>
        <article data-gameday-card="low" data-drama="1"><div data-slug="a" data-priority="1"></div></article>
        <article data-gameday-card="high" data-drama="2"><div data-slug="a" data-priority="9"></div></article>
      </div>`;
    const cards = Array.from(document.querySelectorAll('[data-gameday-card]'));
    for (const card of cards) card.animate = vi.fn();
    const win = fakeWindow({ store: new Map([[ME_KEY, 'a']]) });
    init(document, win);

    expect(Array.from(document.querySelectorAll('[data-gameday-card]'), (card) => card.dataset.gamedayCard))
      .toEqual(['high', 'low']);
    expect(cards.every((card) => card.animate.mock.calls.length === 0)).toBe(true);
  });

  test('the viewer strip measures itself beneath the sticky masthead', () => {
    document.body.innerHTML = '<header class="masthead"></header><div class="viewer-bar"></div>';
    document.querySelector('.masthead').getBoundingClientRect = () => ({ height: 64 });
    document.querySelector('.viewer-bar').getBoundingClientRect = () => ({ height: 48 });
    init(document, fakeWindow());

    expect(document.documentElement.style.getPropertyValue('--masthead-height')).toBe('64px');
    expect(document.documentElement.style.getPropertyValue('--viewer-height')).toBe('48px');
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

// Mid-season by default, so the schedule wiring has a sensible clock without
// every existing test having to care that it now reads one.
const NOW = Date.parse('2026-10-14T15:00:00Z');

function fakeWindow({
  reduceMotion = false,
  prefersDark = true,
  store = new Map(),
  now = NOW,
  innerWidth = 1280,
  innerHeight = 900,
  scrollY = 0,
  observers = [],
} = {}) {
  const frames = [];
  const listeners = new Map();
  return {
    localStorage: {
      getItem: (k) => store.get(k) ?? null,
      setItem: (k, v) => store.set(k, v),
    },
    matchMedia: (query) => ({
      matches: query.includes('reduced-motion') ? reduceMotion : prefersDark,
    }),
    performance: { now: () => 0 },
    Date: { now: () => now },
    requestAnimationFrame: (fn) => frames.push(fn),
    setTimeout: (fn) => fn(),
    addEventListener: (type, fn) => {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    innerWidth,
    innerHeight,
    scrollY,
    devicePixelRatio: 2,
    // Enough of the real thing for the field to read its paint tokens: the
    // canvas asks the document for named colours and never for a computed box.
    getComputedStyle: () => ({ getPropertyValue: (name) => `var-for(${name})` }),
    // Records the callback so a test can play the part of the theme toggle
    // rewriting the attribute the field watches.
    MutationObserver: class {
      constructor(callback) {
        this.callback = callback;
        observers.push(this);
      }

      observe() {}
    },
    // Collected rather than run, so a test can decide when an element is
    // considered to have arrived.
    IntersectionObserver: class {
      constructor(callback) {
        this.callback = callback;
        this.targets = [];
        observers.push(this);
      }

      observe(el) { this.targets.push(el); }

      unobserve(el) { this.targets = this.targets.filter((t) => t !== el); }
    },
    _frames: frames,
    _store: store,
    _observers: observers,
    _fire: (type) => (listeners.get(type) ?? []).forEach((fn) => fn()),
  };
}

describe('init', () => {
  beforeEach(markup);

  test('brings the current primary tab into an overflowing mobile rail', () => {
    document.body.innerHTML = `
      <nav class="tabs">
        <a href="/">Standings</a>
        <a href="/forecast/" aria-current="page">Forecast</a>
      </nav>`;
    const tabs = document.querySelector('.tabs');
    const current = tabs.querySelector('[aria-current]');
    Object.defineProperties(tabs, {
      clientWidth: { configurable: true, value: 240 },
      scrollWidth: { configurable: true, value: 700 },
    });
    tabs.getBoundingClientRect = () => ({ left: 20 });
    current.getBoundingClientRect = () => ({ left: 420, width: 80 });

    init(document, fakeWindow({ reduceMotion: true }));

    expect(tabs.scrollLeft).toBe(320);
  });

  test('the toggle switches the theme and remembers it', () => {
    const win = fakeWindow({ prefersDark: true });
    init(document, win);
    const button = document.querySelector('[data-theme-toggle]');

    expect(button.title).toBe('Switch to light theme');
    expect(button.getAttribute('aria-label')).toBe('Switch to light theme');

    button.click();
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(win._store.get(THEME_KEY)).toBe('light');
    expect(button.title).toBe('Switch to dark theme');
    expect(button.getAttribute('aria-label')).toBe('Switch to dark theme');

    button.click();
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(button.title).toBe('Switch to light theme');
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

  test('a valid zone missing from the list still applies', () => {
    // The select honestly shows no choice, but the stamps render in the
    // stored zone — previously this snapped the viewer back to Eastern and
    // overwrote their stored preference with the emptied select.
    const store = new Map([[TZ_KEY, 'Europe/Berlin']]);
    init(document, fakeWindow({ store }));
    expect(document.querySelector('[data-tz-select]').value).toBe('');
    expect(store.get(TZ_KEY)).toBe('Europe/Berlin');
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

// ---------------------------------------------------------------------------
// "This is me"
// ---------------------------------------------------------------------------
function boardMarkup() {
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('data-me');
  document.body.innerHTML = `
    <div class="row" data-slug="brian-moore"><span class="badge you" data-me-only>you</span></div>
    <div class="row" data-slug="paul-moore"><span class="badge you" data-me-only>you</span></div>
    <select data-me-select>
      <option value="">Nobody in particular</option>
      <option value="brian-moore">Brian Moore</option>
      <option value="paul-moore">Paul Moore</option>
    </select>`;
}

describe('this is me', () => {
  beforeEach(boardMarkup);

  test('choosing a name marks that row and remembers it', () => {
    const win = fakeWindow();
    init(document, win);

    const select = document.querySelector('[data-me-select]');
    select.value = 'paul-moore';
    select.dispatchEvent(new window.Event('change'));

    expect(document.querySelector('[data-slug="paul-moore"]').classList.contains('is-me')).toBe(true);
    expect(document.querySelector('[data-slug="brian-moore"]').classList.contains('is-me')).toBe(false);
    expect(win._store.get(ME_KEY)).toBe('paul-moore');
    expect(document.documentElement.dataset.me).toBe('paul-moore');
  });

  test('a stored identity is restored on the next visit', () => {
    init(document, fakeWindow({ store: new Map([[ME_KEY, 'brian-moore']]) }));
    expect(document.querySelector('[data-me-select]').value).toBe('brian-moore');
    expect(document.querySelector('[data-slug="brian-moore"]').classList.contains('is-me')).toBe(true);
  });

  test('choosing nobody clears the highlight', () => {
    const win = fakeWindow({ store: new Map([[ME_KEY, 'brian-moore']]) });
    init(document, win);

    const select = document.querySelector('[data-me-select]');
    select.value = '';
    select.dispatchEvent(new window.Event('change'));

    expect(document.querySelectorAll('.is-me')).toHaveLength(0);
    expect(win._store.get(ME_KEY)).toBe('');
    expect(document.documentElement.hasAttribute('data-me')).toBe(false);
  });

  test('an identity that has left the pool is discarded, not left dangling', () => {
    // Next season's picks file will not contain last season's entrants, and a
    // stale value must not leave the picker showing a blank selection.
    const win = fakeWindow({ store: new Map([[ME_KEY, 'someone-who-left']]) });
    init(document, win);

    expect(document.querySelector('[data-me-select]').value).toBe('');
    expect(document.querySelectorAll('.is-me')).toHaveLength(0);
    expect(win._store.get(ME_KEY)).toBe('');
  });

  test('pages with no picker still apply a stored identity', () => {
    document.body.innerHTML = '<div class="row" data-slug="brian-moore"></div>';
    init(document, fakeWindow({ store: new Map([[ME_KEY, 'brian-moore']]) }));
    expect(document.querySelector('[data-slug="brian-moore"]').classList.contains('is-me')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// The "your entry" strip
// ---------------------------------------------------------------------------
describe('the strip borrows the row it is built from', () => {
  const board = (rowInner) => {
    document.documentElement.removeAttribute('data-me');
    document.body.innerHTML = `
      <div class="you-strip" data-you hidden></div>
      <div class="board">
        <div class="row" data-slug="brian-moore">
          <span class="row-rank">1</span>
          ${rowInner}
          <span class="row-points">42.00</span>
        </div>
      </div>`;
  };

  test('it takes the destination from the name, not from the row', () => {
    // The row stopped being an anchor when its team chips became links, so
    // there is no href on it any more to borrow.
    board('<a class="row-link" href="/entrant/brian-moore/"><span class="row-name">Brian Moore</span></a>');
    init(document, fakeWindow({ store: new Map([[ME_KEY, 'brian-moore']]) }));

    const strip = document.querySelector('[data-you]');
    expect(strip.hidden).toBe(false);
    const link = strip.querySelector('a');
    expect(link.getAttribute('href')).toBe('/entrant/brian-moore/');
    expect(link.textContent).toContain('Brian Moore');
    expect(link.textContent).toContain('42.00');
  });

  test('a row with nowhere to go leaves no empty bar above the board', () => {
    board('<span class="row-name">Brian Moore</span>');
    init(document, fakeWindow({ store: new Map([[ME_KEY, 'brian-moore']]) }));

    const strip = document.querySelector('[data-you]');
    expect(strip.hidden).toBe(true);
    expect(strip.textContent).toBe('');
  });
});

describe('identity is scoped per pool', () => {
  beforeEach(boardMarkup);

  test('the pool at the site root keeps the unsuffixed key', () => {
    // Which is what lets a returning visitor's saved identity survive the day
    // a second pool appears.
    expect(scopedKey(ME_KEY, '')).toBe('pool-me');
    expect(scopedKey(COMPARE_KEY, '')).toBe('pool-compare');
  });

  test('a pool below the root gets its own key', () => {
    expect(scopedKey(ME_KEY, 'friends')).toBe('pool-me:friends');
    expect(scopedKey(COMPARE_KEY, 'friends')).toBe('pool-compare:friends');
  });

  test('one pool does not erase who you are in another', () => {
    // The bug this prevents: localStorage is per origin, so both pools share a
    // store. Landing on a pool whose picker has no such entrant used to write
    // '' straight over the other pool's answer, and you came back a stranger.
    document.documentElement.dataset.pool = 'friends';
    const win = fakeWindow({ store: new Map([[ME_KEY, 'brian-moore']]) });
    init(document, win);

    expect(win._store.get(ME_KEY)).toBe('brian-moore');
    expect(document.querySelector('[data-me-select]').value).toBe('');
  });

  test('a choice made in one pool is stored under that pool', () => {
    document.documentElement.dataset.pool = 'friends';
    const win = fakeWindow();
    init(document, win);

    const select = document.querySelector('[data-me-select]');
    select.value = 'paul-moore';
    select.dispatchEvent(new window.Event('change'));

    expect(win._store.get('pool-me:friends')).toBe('paul-moore');
    expect(win._store.has(ME_KEY)).toBe(false);
  });

  test('viewer preferences stay global — they follow you across pools', () => {
    document.documentElement.dataset.pool = 'friends';
    const win = fakeWindow();
    init(document, win);

    document.querySelector('[data-theme-toggle]')?.click();
    // Whatever theme/tz end up as, they are never namespaced.
    for (const key of win._store.keys()) {
      expect(key.startsWith('pool-theme:')).toBe(false);
      expect(key.startsWith('pool-tz:')).toBe(false);
      expect(key.startsWith('pool-detail:')).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// Comparison chart
// ---------------------------------------------------------------------------
function compareMarkup(slugs = ['brian-moore', 'paul-moore', 'brenda-moore']) {
  document.documentElement.removeAttribute('data-me');
  const picks = slugs
    .map((s) => `<button class="pick" data-pick="${s}" aria-pressed="false">${s}</button>`)
    .join('');
  const lines = slugs
    .map(
      (s, i) =>
        `<polyline class="cmp-line" data-entrant="${s}"></polyline>` +
        `<circle class="cmp-dot" data-entrant="${s}"></circle>` +
        `<text class="cmp-label" data-entrant="${s}" data-y="${40 + i * 2}"></text>`,
    )
    .join('');
  document.body.innerHTML = `
    <div class="compare-picks">${picks}</div>
    <p data-compare-empty>nothing picked</p>
    <div data-compare><svg>${lines}</svg></div>`;
}

const pickedSlugs = () =>
  [...document.querySelectorAll('.cmp-line.is-picked')].map((el) => el.dataset.entrant);

describe('comparison chart', () => {
  beforeEach(() => compareMarkup());

  test('nothing is picked by default and the prompt is visible', () => {
    init(document, fakeWindow());
    expect(pickedSlugs()).toEqual([]);
    expect(document.querySelector('[data-compare-empty]').hidden).toBe(false);
  });

  test('picking someone lights their line, dot and label together', () => {
    const win = fakeWindow();
    init(document, win);
    document.querySelector('[data-pick="paul-moore"]').click();

    expect(pickedSlugs()).toEqual(['paul-moore']);
    for (const cls of ['.cmp-line', '.cmp-dot', '.cmp-label']) {
      const el = document.querySelector(`${cls}[data-entrant="paul-moore"]`);
      expect(el.classList.contains('is-picked')).toBe(true);
      expect(el.style.getPropertyValue('--pick-color')).toBe(PICK_COLORS[0]);
    }
    expect(document.querySelector('[data-pick="paul-moore"]').getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelector('[data-compare-empty]').hidden).toBe(true);
    expect(win._store.get(COMPARE_KEY)).toBe('paul-moore');
  });

  test('colours follow pick order, so the first pick is always the first colour', () => {
    init(document, fakeWindow());
    document.querySelector('[data-pick="brenda-moore"]').click();
    document.querySelector('[data-pick="brian-moore"]').click();

    const color = (slug) =>
      document.querySelector(`.cmp-line[data-entrant="${slug}"]`).style.getPropertyValue('--pick-color');
    expect(color('brenda-moore')).toBe(PICK_COLORS[0]);
    expect(color('brian-moore')).toBe(PICK_COLORS[1]);
  });

  test('clicking again unpicks and clears the colour', () => {
    init(document, fakeWindow());
    const button = document.querySelector('[data-pick="brian-moore"]');
    button.click();
    button.click();

    expect(pickedSlugs()).toEqual([]);
    expect(button.getAttribute('aria-pressed')).toBe('false');
    const line = document.querySelector('.cmp-line[data-entrant="brian-moore"]');
    expect(line.style.getPropertyValue('--pick-color')).toBe('');
  });

  test('past the palette the oldest pick drops rather than reusing a colour', () => {
    const many = Array.from({ length: PICK_COLORS.length + 1 }, (_, i) => `p${i}`);
    compareMarkup(many);
    init(document, fakeWindow());
    for (const slug of many) document.querySelector(`[data-pick="${slug}"]`).click();

    const picked = pickedSlugs();
    expect(picked).toHaveLength(PICK_COLORS.length);
    expect(picked).not.toContain('p0'); // the first one picked made way
    expect(new Set(picked.map((s) =>
      document.querySelector(`.cmp-line[data-entrant="${s}"]`).style.getPropertyValue('--pick-color'),
    )).size).toBe(PICK_COLORS.length);
  });

  test('it opens on your own line once you have said who you are', () => {
    // The whole chain: the stored identity is applied by initMe, and initCompare
    // reads it from the document. Order matters here — initMe writes the
    // attribute that initCompare then reads — so this covers the wiring too.
    init(document, fakeWindow({ store: new Map([[ME_KEY, 'brenda-moore']]) }));
    expect(pickedSlugs()).toEqual(['brenda-moore']);
  });

  test('a stored selection beats the identity default', () => {
    const store = new Map([
      [ME_KEY, 'brenda-moore'],
      [COMPARE_KEY, 'brian-moore paul-moore'],
    ]);
    init(document, fakeWindow({ store }));
    expect(pickedSlugs().sort()).toEqual(['brian-moore', 'paul-moore']);
  });

  test('stored names that are no longer in the pool are dropped', () => {
    init(document, fakeWindow({ store: new Map([[COMPARE_KEY, 'ghost brian-moore']]) }));
    expect(pickedSlugs()).toEqual(['brian-moore']);
  });

  test('colliding endpoint labels are pushed apart, dots stay put', () => {
    document.body.innerHTML = `
      <div class="compare-picks">
        <button class="pick" data-pick="a" aria-pressed="false">a</button>
        <button class="pick" data-pick="b" aria-pressed="false">b</button>
      </div>
      <div data-compare><svg>
        <polyline class="cmp-line" data-entrant="a"></polyline>
        <text class="cmp-label" data-entrant="a" data-y="50"></text>
        <polyline class="cmp-line" data-entrant="b"></polyline>
        <text class="cmp-label" data-entrant="b" data-y="50"></text>
      </svg></div>`;
    init(document, fakeWindow());
    document.querySelector('[data-pick="a"]').click();
    document.querySelector('[data-pick="b"]').click();

    const ys = [...document.querySelectorAll('.cmp-label')].map((el) => Number(el.getAttribute('y')));
    expect(new Set(ys).size).toBe(2);
    expect(Math.abs(ys[0] - ys[1])).toBeGreaterThanOrEqual(14);
  });

  test('a page with no chart does not throw', () => {
    document.body.innerHTML = '<p>no chart here</p>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// Sortable tables
// ---------------------------------------------------------------------------
describe('sortable table headers', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table>
        <thead><tr><th data-sort>Team</th><th data-sort>Points</th></tr></thead>
        <tbody>
          <tr><th data-value="ARI">ARI</th><td data-value="4">4.00</td></tr>
          <tr><th data-value="KC">KC</th><td data-value="30">30.00</td></tr>
          <tr><th data-value="DAL">DAL</th><td data-value="12">12.00</td></tr>
        </tbody>
      </table>`;
  });

  const column = (i) => [...document.querySelectorAll('tbody tr')].map((r) => r.children[i].textContent);

  test('clicking a heading sorts by it and marks the direction', () => {
    init(document, fakeWindow());
    const th = document.querySelectorAll('th[data-sort]')[1];
    expect(th.title).toBe('Sort by Points, ascending');
    th.click();

    expect(column(1)).toEqual(['4.00', '12.00', '30.00']);
    expect(th.getAttribute('aria-sort')).toBe('ascending');
    expect(th.title).toBe('Sort by Points, descending');
  });

  test('clicking the same heading again reverses it', () => {
    init(document, fakeWindow());
    const th = document.querySelectorAll('th[data-sort]')[1];
    th.click();
    th.click();

    expect(column(1)).toEqual(['30.00', '12.00', '4.00']);
    expect(th.getAttribute('aria-sort')).toBe('descending');
  });

  test('a numeric column opens biggest-first', () => {
    // Templates mark number columns with class="num"; those lead with the
    // biggest value — a points column is useless smallest-first.
    document.querySelectorAll('th[data-sort]')[1].classList.add('num');
    init(document, fakeWindow());
    const th = document.querySelectorAll('th[data-sort]')[1];
    th.click();

    expect(column(1)).toEqual(['30.00', '12.00', '4.00']);
    expect(th.getAttribute('aria-sort')).toBe('descending');

    th.click();
    expect(column(1)).toEqual(['4.00', '12.00', '30.00']);
    expect(th.getAttribute('aria-sort')).toBe('ascending');
  });

  test('sorting a different column clears the previous marker', () => {
    init(document, fakeWindow());
    const [first, second] = document.querySelectorAll('th[data-sort]');
    second.click();
    first.click();

    expect(column(0)).toEqual(['ARI', 'DAL', 'KC']);
    expect(second.hasAttribute('aria-sort')).toBe(false);
    expect(first.getAttribute('aria-sort')).toBe('ascending');
  });

  test('headings are reachable and operable from the keyboard', () => {
    init(document, fakeWindow());
    const th = document.querySelectorAll('th[data-sort]')[1];
    expect(th.tabIndex).toBe(0);

    th.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(column(1)).toEqual(['4.00', '12.00', '30.00']);

    th.dispatchEvent(new window.KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(column(1)).toEqual(['30.00', '12.00', '4.00']);
  });

  test('an explicit expansion supplies the tooltip label', () => {
    const th = document.querySelectorAll('th[data-sort]')[1];
    th.title = 'Points generated';
    init(document, fakeWindow());

    expect(th.title).toBe('Sort by Points generated, ascending');
  });

  test('other keys are ignored', () => {
    init(document, fakeWindow());
    const th = document.querySelectorAll('th[data-sort]')[1];
    th.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    expect(column(1)).toEqual(['4.00', '30.00', '12.00']);
  });

  test('a table with no sortable headings is left alone', () => {
    document.body.innerHTML = '<table><thead><tr><th>x</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>';
    expect(() => init(document, fakeWindow())).not.toThrow();
    expect(document.querySelector('th').tabIndex).toBe(-1);
  });
});

describe('only the games that matter', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-slate');
    document.body.innerHTML = `
      <button data-slate-toggle aria-pressed="false">Pool games only</button>
      <ul class="games">
        <li class="game"><button data-game-open aria-expanded="false"></button>
          <div class="game-more"></div></li>
        <li class="game is-idle"><button data-game-open aria-expanded="false"></button>
          <div class="game-more"></div></li>
      </ul>`;
  });

  test('the filter is one temporary attribute on the root', () => {
    const win = fakeWindow();
    init(document, win);
    const button = document.querySelector('[data-slate-toggle]');

    button.click();
    expect(document.documentElement.dataset.slate).toBe('pool');
    expect(button.getAttribute('aria-pressed')).toBe('true');

    button.click();
    expect(document.documentElement.dataset.slate).toBeUndefined();
    expect(button.getAttribute('aria-pressed')).toBe('false');
    expect(win._store.has('pool-slate')).toBe(false);
  });

  test('every page visit defaults back to every NFL game', () => {
    // Clear an attribute left by a cached copy of the older, remembered filter.
    document.documentElement.dataset.slate = 'pool';
    init(document, fakeWindow());

    expect(document.querySelector('[data-slate-toggle]').getAttribute('aria-pressed'))
      .toBe('false');
    expect(document.documentElement.dataset.slate).toBeUndefined();
  });

  test('a page without the filter is left alone', () => {
    document.body.innerHTML = '<ul class="games"></ul>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});

describe('opening a game up', () => {
  const gameMarkup = () => {
    document.body.innerHTML = `
      <ul class="games">
        <li class="game" id="game-G1" data-game="G1">
          <div class="game-when"><time>Sun</time></div>
          <div class="game-side"><a class="team-chip" href="/team/KC/">KC</a>
            <span class="owners"><a class="owner" href="/entrant/bo/">Bo</a></span></div>
          <button class="game-open" type="button" data-game-open
                  aria-expanded="false" aria-controls="more-G1"></button>
          <div class="game-more" id="more-G1">what it is worth</div>
        </li>
        <li class="game" data-game="G2">
          <div class="game-when"><time>Mon</time></div>
          <button class="game-open" type="button" data-game-open aria-expanded="false"></button>
          <div class="game-more">and this one</div>
        </li>
      </ul>`;
  };

  const rows = () => Array.from(document.querySelectorAll('.game'));
  const click = (el) => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

  beforeEach(() => {
    gameMarkup();
    init(document, fakeWindow());
  });

  test('the button opens the panel and says so', () => {
    const [row] = rows();
    const button = row.querySelector('[data-game-open]');
    expect(button.title).toBe('Show what this game is worth');
    click(button);

    expect(row.classList.contains('is-open')).toBe(true);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(button.title).toBe('Hide what this game is worth');

    click(button);
    expect(row.classList.contains('is-open')).toBe(false);
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(button.title).toBe('Show what this game is worth');
  });

  test('an exact matchup link arrives with the head-to-head facts open', () => {
    window.location.hash = '#game-G1';
    gameMarkup();
    init(document, fakeWindow());

    const [row] = rows();
    expect(row.matches(':target')).toBe(true);
    expect(row.classList.contains('is-open')).toBe(true);
    expect(row.querySelector('[data-game-open]').getAttribute('aria-expanded')).toBe('true');
    expect(row.querySelector('[data-game-open]').title).toBe('Hide what this game is worth');
    window.location.hash = '';
  });

  test('a malformed matchup hash cannot break the schedule', () => {
    window.location.hash = '#game-%E0%A4%A';
    gameMarkup();
    expect(() => init(document, fakeWindow())).not.toThrow();
    expect(document.querySelectorAll('.game.is-open')).toHaveLength(0);
    window.location.hash = '';
  });

  test('clicking the row anywhere else opens it too', () => {
    const [row] = rows();
    click(row.querySelector('.game-when time'));
    expect(row.classList.contains('is-open')).toBe(true);
  });

  test('but never when the click was on a link', () => {
    // A chip goes to the team's page and a name to that person's. Opening a
    // panel underneath the page you are leaving is a bug, not a bonus.
    // Navigation is cancelled only to keep jsdom quiet about it.
    const [row] = rows();
    const quietly = (el) => {
      el.addEventListener('click', (event) => event.preventDefault());
      click(el);
    };

    quietly(row.querySelector('a.team-chip'));
    expect(row.classList.contains('is-open')).toBe(false);

    quietly(row.querySelector('a.owner'));
    expect(row.classList.contains('is-open')).toBe(false);
  });

  test('and never while text is being selected', () => {
    const [row] = rows();
    const selection = window.getSelection;
    window.getSelection = () => ({ toString: () => '2.15' });
    try {
      click(row.querySelector('.game-when time'));
      expect(row.classList.contains('is-open')).toBe(false);
    } finally {
      window.getSelection = selection;
    }
  });

  test('one game at a time is a choice the reader makes, not the page', () => {
    const [first, second] = rows();
    click(first.querySelector('.game-when'));
    click(second.querySelector('.game-when'));

    expect(first.classList.contains('is-open')).toBe(true);
    expect(second.classList.contains('is-open')).toBe(true);
  });

  test('a click outside any game does nothing at all', () => {
    click(document.querySelector('.games'));
    expect(document.querySelectorAll('.game.is-open')).toHaveLength(0);
  });

  test('a game row with no panel is not made interactive', () => {
    document.body.innerHTML = '<ul class="games"><li class="game"><time>x</time></li></ul>';
    init(document, fakeWindow());
    click(document.querySelector('.game time'));

    expect(document.querySelector('.game').classList.contains('is-open')).toBe(false);
  });
});

describe('weekForInstant', () => {
  // Three weeks, each closing just before the next opens.
  const WINDOWS = [
    { week: '1', closesMs: Date.parse('2026-09-15T03:45:00Z') },
    { week: '2', closesMs: Date.parse('2026-09-22T03:45:00Z') },
    { week: '3', closesMs: Date.parse('2026-09-29T03:45:00Z') },
  ];

  test('picks the week that has not finished yet', () => {
    expect(weekForInstant(WINDOWS, Date.parse('2026-09-20T18:00:00Z'))).toBe('2');
  });

  test('rolls over the moment a week closes', () => {
    expect(weekForInstant(WINDOWS, Date.parse('2026-09-15T03:44:00Z'))).toBe('1');
    expect(weekForInstant(WINDOWS, Date.parse('2026-09-15T03:46:00Z'))).toBe('2');
  });

  test('before the season, the first week is upcoming', () => {
    expect(weekForInstant(WINDOWS, Date.parse('2026-08-13T12:00:00Z'))).toBe('1');
  });

  test('after the season, the last week stays put', () => {
    // Not null and not week 1 — the last thing that happened is what you want.
    expect(weekForInstant(WINDOWS, Date.parse('2027-03-01T12:00:00Z'))).toBe('3');
  });

  test('an empty schedule has no answer', () => {
    expect(weekForInstant([], Date.now())).toBeNull();
  });

  test('a section with an unreadable date is skipped, not fatal', () => {
    const broken = [{ week: '1', closesMs: Number.NaN }, ...WINDOWS.slice(1)];
    expect(weekForInstant(broken, Date.parse('2026-09-01T12:00:00Z'))).toBe('2');
    expect(weekForInstant([{ week: '1', closesMs: Number.NaN }], Date.now())).toBeNull();
  });
});

function scheduleMarkup() {
  document.documentElement.removeAttribute('data-me');
  document.body.innerHTML = `
    <nav class="week-switch">
      <a href="#preseason" data-week-link="preseason">PRE</a>
      <a href="#week-1" data-week-link="1">1</a>
      <a href="#week-2" data-week-link="2">2</a>
      <a href="#week-3" data-week-link="3">3</a>
    </nav>
    <div class="weeks">
      <section class="week" data-week="1" data-closes="2026-09-15T03:45:00+00:00">
        <time datetime="2026-09-14T00:20:00+00:00" data-ts="kickoff">raw</time>
      </section>
      <section class="week is-default" data-week="2" data-closes="2026-09-22T03:45:00+00:00"></section>
      <section class="week" data-week="3" data-closes="2026-09-29T03:45:00+00:00"></section>
    </div>`;
}

const openWeek = () =>
  document.querySelector('.week.is-default')?.dataset.week ?? null;

describe('the schedule week switcher', () => {
  beforeEach(() => {
    scheduleMarkup();
    window.location.hash = '';
  });

  test("the build's choice stands when the clock agrees with it", () => {
    init(document, fakeWindow({ now: Date.parse('2026-09-20T18:00:00Z') }));

    expect(openWeek()).toBe('2');
    expect(document.querySelectorAll('.week.is-default')).toHaveLength(1);
  });

  test('a stale default is corrected to the visitor\'s own week', () => {
    // The overnight case: the week rolled over at 23:45 Monday and the site
    // has not rebuilt yet. The page still opens on the right week.
    init(document, fakeWindow({ now: Date.parse('2026-09-27T18:00:00Z') }));

    expect(openWeek()).toBe('3');
    expect(document.querySelectorAll('.week.is-default')).toHaveLength(1);
  });

  test('the current week is marked in the switcher', () => {
    init(document, fakeWindow({ now: Date.parse('2026-09-20T18:00:00Z') }));

    const now = Array.from(document.querySelectorAll('.is-now'));
    expect(now.map((a) => a.dataset.weekLink)).toEqual(['2']);
  });

  test('following a deep link marks that week as the one being read', () => {
    window.location.hash = '#week-3';
    init(document, fakeWindow({ now: Date.parse('2026-09-20T18:00:00Z') }));

    const current = document.querySelector('[data-week-link][aria-current]');
    expect(current.dataset.weekLink).toBe('3');
    // ...without moving which week is "now". They are different questions.
    expect(document.querySelector('.is-now').dataset.weekLink).toBe('2');
  });

  test('the preseason deep link marks PRE without changing the current regular week', () => {
    window.location.hash = '#preseason';
    init(document, fakeWindow({ now: Date.parse('2026-09-20T18:00:00Z') }));

    expect(document.querySelector('[data-week-link][aria-current]').dataset.weekLink)
      .toBe('preseason');
    expect(document.querySelector('.is-now').dataset.weekLink).toBe('2');
  });

  test('with no hash, the current week is the one being read', () => {
    init(document, fakeWindow({ now: Date.parse('2026-09-20T18:00:00Z') }));

    expect(document.querySelector('[data-week-link][aria-current]').dataset.weekLink).toBe('2');
  });

  test('brings a deep-linked week into an overflowing mobile rail', () => {
    window.location.hash = '#week-3';
    const rail = document.querySelector('.week-switch');
    const week = document.querySelector('[data-week-link="3"]');
    Object.defineProperties(rail, {
      clientWidth: { configurable: true, value: 100 },
      scrollWidth: { configurable: true, value: 400 },
    });
    rail.getBoundingClientRect = () => ({ left: 10 });
    week.getBoundingClientRect = () => ({ left: 330, width: 40 });

    init(document, fakeWindow({ now: Date.parse('2026-09-20T18:00:00Z') }));

    expect(rail.scrollLeft).toBe(290);
  });

  test('a page with no schedule on it does not throw', () => {
    document.body.innerHTML = '<p>nothing here</p>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});

describe('kickoff stamps', () => {
  beforeEach(scheduleMarkup);

  test('a kickoff carries its weekday, because football is scheduled by day', () => {
    init(document, fakeWindow());

    const text = document.querySelector('time[data-ts="kickoff"]').textContent;
    // 8:20pm Eastern on Sunday the 13th — the UTC instant is Monday, so a
    // server-rendered weekday would have been wrong here.
    expect(text).toMatch(/^Sun,/);
    expect(text).toContain('8:20');
    expect(text).toContain('EDT');
  });

  test('a footer stamp does not, because a weekday there says nothing', () => {
    expect(formatTimestamp(ISO, 'America/New_York')).not.toMatch(/^[A-Z][a-z]{2},/);
  });

  test('an unusable zone still falls back after the formatter cache warms up', () => {
    // Caching a failure would turn one bad lookup into a permanently broken
    // stamp, so only successful formatters are remembered.
    expect(formatTimestamp(ISO, 'Mars/Olympus')).toBe(ISO);
    expect(formatTimestamp(ISO, 'Mars/Olympus')).toBe(ISO);
    expect(formatTimestamp(ISO, 'UTC')).toContain('UTC');
  });
});

// ---------------------------------------------------------------------------
// The gridiron
// ---------------------------------------------------------------------------

/**
 * A 2D context that records instead of drawing.
 *
 * The field's drawing code takes a context rather than fetching one, precisely
 * so it can be handed this — every decision it makes about where a goal line
 * lands or which numbers get painted is then an assertion, with no rendering
 * engine anywhere in the test.
 */
function recordingContext() {
  const calls = [];
  const state = { fillStyle: '', strokeStyle: '', lineWidth: 0, font: '' };
  const record = (name) => (...args) => calls.push({
    name,
    args,
    fill: state.fillStyle,
    stroke: state.strokeStyle,
    width: state.lineWidth,
    font: state.font,
  });
  return {
    calls,
    get fillStyle() { return state.fillStyle; },
    set fillStyle(v) { state.fillStyle = v; },
    get strokeStyle() { return state.strokeStyle; },
    set strokeStyle(v) { state.strokeStyle = v; },
    get lineWidth() { return state.lineWidth; },
    set lineWidth(v) { state.lineWidth = v; },
    get font() { return state.font; },
    set font(v) { state.font = v; },
    textBaseline: '',
    textAlign: '',
    clearRect: record('clearRect'),
    fillRect: record('fillRect'),
    strokeRect: record('strokeRect'),
    beginPath: record('beginPath'),
    moveTo: record('moveTo'),
    lineTo: record('lineTo'),
    stroke: record('stroke'),
    fillText: record('fillText'),
    save: record('save'),
    restore: record('restore'),
    translate: record('translate'),
    rotate: record('rotate'),
    setTransform: record('setTransform'),
  };
}

const PAINT = {
  turfA: '#turf-a',
  turfB: '#turf-b',
  chalk: '#chalk',
  chalkStrong: '#chalk-strong',
  number: '#number',
  hash: '#hash',
  endZone: '#end-zone',
  wordmark: '#wordmark',
  pylon: '#pylon',
  display: 'Display',
};

describe('field geometry', () => {
  test('the field is 120 yards of it, end zone to end zone', () => {
    expect(FIELD_YARDS).toBe(120);
    expect(END_ZONE_YARDS).toBe(10);

    const geom = fieldGeometry(400, 840);
    expect(geom.yard).toBeCloseTo(7);
    // Both goal lines are on screen, which is the whole promise.
    expect(yardToY(geom, END_ZONE_YARDS)).toBeCloseTo(70);
    expect(yardToY(geom, FIELD_YARDS - END_ZONE_YARDS)).toBeCloseTo(770);
    expect(yardToY(geom, FIELD_YARDS)).toBeCloseTo(840);
  });

  test('the sidelines are inset proportionally, then capped', () => {
    // A phone gets a proportional margin; a wide desktop would otherwise push
    // the sidelines absurdly far in and squash the field.
    expect(fieldGeometry(400, 840).inset).toBeCloseTo(22);
    expect(fieldGeometry(1600, 900).inset).toBe(26);
  });

  test('yard numbers count towards the nearer goal line, as a field paints them', () => {
    expect(markerNumber(20)).toBe(10);
    expect(markerNumber(60)).toBe(50); // midfield
    expect(markerNumber(100)).toBe(10);
    // Symmetrical about the fifty, which is the property that makes them right.
    expect(markerNumber(30)).toBe(markerNumber(90));
  });
});

describe('drawField', () => {
  const geom = fieldGeometry(1000, 1200);
  let ctx;

  beforeEach(() => {
    ctx = recordingContext();
    drawField(ctx, geom, PAINT, { near: 'Family Pool', far: '2026' });
  });

  const called = (name) => ctx.calls.filter((c) => c.name === name);

  test('both goal lines are drawn, and drawn more strongly than a yard line', () => {
    const strong = called('moveTo').filter((c) => c.stroke === PAINT.chalkStrong);
    const ys = strong.map((c) => c.args[1]);
    expect(ys).toContain(yardToY(geom, 10));
    expect(ys).toContain(yardToY(geom, 110));
    expect(strong.every((c) => c.width > 1)).toBe(true);
  });

  test('yard lines land every five yards, and never inside an end zone', () => {
    const chalk = called('moveTo')
      .filter((c) => c.stroke === PAINT.chalk)
      .map((c) => c.args[1] / geom.yard);
    expect(chalk.length).toBeGreaterThan(0);
    for (const yards of chalk) {
      expect(Math.round(yards) % 5).toBe(0);
      expect(yards).toBeGreaterThan(END_ZONE_YARDS);
      expect(yards).toBeLessThan(FIELD_YARDS - END_ZONE_YARDS);
    }
  });

  test('the numbers are painted in pairs, turned to face their own sideline', () => {
    const numbers = called('fillText').filter((c) => c.fill === PAINT.number);
    // 10 through 50 and back down again, twice — once per sideline.
    expect(numbers).toHaveLength(9 * 2);
    expect(numbers.map((c) => c.args[0])).toContain('50');

    const angles = called('rotate').map((c) => c.args[0]);
    expect(angles).toContain(Math.PI / 2);
    expect(angles).toContain(-Math.PI / 2);
  });

  test('each end zone carries its own wordmark', () => {
    const marks = called('fillText')
      .filter((c) => c.fill === PAINT.wordmark)
      .map((c) => c.args[0]);
    expect(marks).toEqual(['FAMILY POOL', '2026']);
  });

  test('an end zone with nothing to say is left empty rather than blank-painted', () => {
    const bare = recordingContext();
    drawField(bare, geom, PAINT, {});
    expect(bare.calls.filter((c) => c.fill === PAINT.wordmark)).toHaveLength(0);
  });

  test('hash marks are skipped when a yard is too few pixels to show one', () => {
    const roomy = recordingContext();
    drawField(roomy, fieldGeometry(1000, 1200), PAINT);
    expect(roomy.calls.some((c) => c.stroke === PAINT.hash)).toBe(true);

    // A short viewport puts the yards about four pixels apart, where four rows
    // of ticks per yard is noise rather than texture.
    const cramped = recordingContext();
    drawField(cramped, fieldGeometry(1000, 480), PAINT);
    expect(cramped.calls.some((c) => c.stroke === PAINT.hash)).toBe(false);
  });

  test('eight pylons, one per end-zone corner', () => {
    expect(called('fillRect').filter((c) => c.fill === PAINT.pylon)).toHaveLength(8);
  });

  test('the turf is striped every five yards, alternating', () => {
    const bands = called('fillRect').filter(
      (c) => c.fill === PAINT.turfA || c.fill === PAINT.turfB,
    );
    expect(bands).toHaveLength(FIELD_YARDS / 5);
    expect(bands[0].fill).toBe(PAINT.turfA);
    expect(bands[1].fill).toBe(PAINT.turfB);
  });

  test('the canvas is cleared first, so a repaint is not painted over the last one', () => {
    expect(ctx.calls[0].name).toBe('clearRect');
  });
});

describe('fieldPalette', () => {
  test('every colour is read from the document, so the theme owns all of them', () => {
    const paint = fieldPalette({ getPropertyValue: (name) => ` ${name} ` });
    expect(paint.chalk).toBe('--paint-chalk');
    expect(paint.endZone).toBe('--paint-endzone');
    expect(paint.pylon).toBe('--paint-pylon');
  });

  test('a stylesheet that has not loaded yet still yields a drawable field', () => {
    const paint = fieldPalette({ getPropertyValue: () => '' });
    expect(paint.turfA).toBeTruthy();
    expect(paint.display).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// How old is this?
// ---------------------------------------------------------------------------
describe('relativeAge', () => {
  const at = (iso) => Date.parse(iso);
  const BUILT = '2026-09-20T12:00:00Z';

  test('coarse on purpose — a twice-daily scoreboard does not need minutes', () => {
    expect(relativeAge(BUILT, at('2026-09-20T12:00:30Z'))).toBe('just now');
    expect(relativeAge(BUILT, at('2026-09-20T12:40:00Z'))).toBe('40m ago');
    expect(relativeAge(BUILT, at('2026-09-20T21:42:00Z'))).toBe('9h ago');
    expect(relativeAge(BUILT, at('2026-09-23T12:00:00Z'))).toBe('3d ago');
  });

  test('hours run to two days before rolling over, so "36h ago" stays sayable', () => {
    expect(relativeAge(BUILT, at('2026-09-21T23:00:00Z'))).toBe('35h ago');
    expect(relativeAge(BUILT, at('2026-09-22T13:00:00Z'))).toBe('2d ago');
  });

  test('a stamp from the future is a clock disagreement, not the reader\'s problem', () => {
    expect(relativeAge(BUILT, at('2026-09-20T11:00:00Z'))).toBe('just now');
  });

  test('an unreadable stamp has no age at all', () => {
    expect(relativeAge('not a date', Date.now())).toBeNull();
  });
});

describe('isStale', () => {
  const BUILT = '2026-09-20T12:00:00Z';

  test('a day is the line', () => {
    expect(STALE_AFTER_HOURS).toBe(24);
    expect(isStale(BUILT, Date.parse('2026-09-21T06:00:00Z'))).toBe(false);
    expect(isStale(BUILT, Date.parse('2026-09-21T18:00:00Z'))).toBe(true);
  });

  test('an unreadable stamp is not accused of being stale', () => {
    expect(isStale('nonsense', Date.now())).toBe(false);
  });
});

describe('the freshness strip', () => {
  const freshMarkup = (iso) => {
    document.body.innerHTML = `
      <div class="viewer-bar">
        <p class="freshness">
          <span class="fresh-item"><time datetime="${iso}" data-ts data-age>raw</time></span>
          <span class="fresh-item"><time datetime="${iso}" data-ts>raw</time></span>
        </p>
        <select data-tz-select><option value="America/New_York">Eastern</option></select>
      </div>`;
  };

  test('the data stamp gets an age badge and the build stamp does not', () => {
    freshMarkup('2026-09-20T12:00:00+00:00');
    init(document, fakeWindow({ now: Date.parse('2026-09-20T17:00:00Z') }));

    const badges = document.querySelectorAll('.fresh-age');
    expect(badges).toHaveLength(1);
    expect(badges[0].textContent).toBe('5h ago');
    expect(badges[0].classList.contains('is-stale')).toBe(false);
  });

  test('old data is flagged, because a quietly stale scoreboard is the worst kind', () => {
    freshMarkup('2026-09-18T12:00:00+00:00');
    init(document, fakeWindow({ now: Date.parse('2026-09-20T17:00:00Z') }));

    const badge = document.querySelector('.fresh-age');
    expect(badge.textContent).toBe('2d ago');
    expect(badge.classList.contains('is-stale')).toBe(true);
  });

  test('the badge survives a change of time zone rather than being wiped by it', () => {
    freshMarkup('2026-09-20T12:00:00+00:00');
    init(document, fakeWindow({ now: Date.parse('2026-09-20T17:00:00Z') }));

    const select = document.querySelector('[data-tz-select]');
    select.value = 'America/New_York';
    select.dispatchEvent(new window.Event('change'));

    // Exactly one: repainting must not leave two badges stacked up either.
    expect(document.querySelectorAll('.fresh-age')).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Definitions
// ---------------------------------------------------------------------------
describe('tooltipPosition', () => {
  const VIEWPORT = { width: 400, height: 800 };
  const SIZE = { width: 300, height: 120 };
  const anchorAt = (top, left) => ({ top, left, bottom: top + 15, width: 15 });

  test('below the button when there is room', () => {
    const spot = tooltipPosition(anchorAt(100, 200), SIZE, VIEWPORT);
    expect(spot.flipped).toBe(false);
    expect(spot.top).toBe(123);
  });

  test('above it when there is not', () => {
    const spot = tooltipPosition(anchorAt(700, 200), SIZE, VIEWPORT);
    expect(spot.flipped).toBe(true);
    expect(spot.top).toBe(700 - 8 - 120);
  });

  test('a definition that fits neither way is pinned inside the viewport', () => {
    const tall = { width: 300, height: 700 };
    const spot = tooltipPosition(anchorAt(600, 200), tall, VIEWPORT);
    expect(spot.flipped).toBe(false);
    expect(spot.top).toBe(92); // 800 - 700 - 8, still fully on screen
  });

  test('slid sideways so it never hangs off an edge — the phone case', () => {
    // A tooltip nearly as wide as the screen, anchored hard right.
    expect(tooltipPosition(anchorAt(100, 390), SIZE, VIEWPORT).left).toBe(92);
    expect(tooltipPosition(anchorAt(100, 2), SIZE, VIEWPORT).left).toBe(8);
  });

  test('centred on the button when the room is there', () => {
    const wide = { width: 1200, height: 900 };
    const spot = tooltipPosition(anchorAt(100, 600), SIZE, wide);
    expect(spot.left).toBe(600 + 7.5 - 150);
  });
});

describe('the definition popovers', () => {
  const glossaryMarkup = () => {
    document.body.innerHTML = `
      <main>
        <p class="stat-label">On the table<span class="term">
          <button class="info" type="button" aria-expanded="false">
            <span class="visually-hidden">On the table: the most the pool could bank.</span>
          </button>
          <span class="def" role="tooltip"><b class="def-term">On the table</b></span>
        </span></p>
        <p class="stat-label">Locked in<span class="term">
          <button class="info" type="button" aria-expanded="false"></button>
          <span class="def" role="tooltip"></span>
        </span></p>
      </main>`;
    // jsdom lays nothing out, so every box would otherwise be zero-sized.
    for (const el of document.querySelectorAll('.info, .def')) {
      el.getBoundingClientRect = () => ({
        top: 100, left: 200, bottom: 115, width: 15, height: 15,
      });
    }
  };

  const terms = () => Array.from(document.querySelectorAll('.term'));

  beforeEach(() => {
    glossaryMarkup();
    init(document, fakeWindow());
  });

  test('hovering opens the definition and places it in the viewport', () => {
    const [first] = terms();
    first.dispatchEvent(new window.Event('pointerenter'));

    expect(first.classList.contains('is-open')).toBe(true);
    expect(first.querySelector('.info').getAttribute('aria-expanded')).toBe('true');
    expect(first.querySelector('.def').style.top).toBeTruthy();
  });

  test('a tap toggles it, which is the case a CSS-only tooltip cannot serve', () => {
    const [first] = terms();
    const button = first.querySelector('.info');

    button.dispatchEvent(new window.Event('click'));
    expect(first.classList.contains('is-open')).toBe(true);

    button.dispatchEvent(new window.Event('click'));
    expect(first.classList.contains('is-open')).toBe(false);
  });

  test('only one is ever open — two overlapping definitions explain nothing', () => {
    const [first, second] = terms();
    first.dispatchEvent(new window.Event('pointerenter'));
    second.dispatchEvent(new window.Event('pointerenter'));

    expect(first.classList.contains('is-open')).toBe(false);
    expect(second.classList.contains('is-open')).toBe(true);
  });

  test('escape closes it', () => {
    const [first] = terms();
    first.dispatchEvent(new window.Event('pointerenter'));
    document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' }));

    expect(first.classList.contains('is-open')).toBe(false);
  });

  test('the definition is the button\'s accessible name, so it needs no opening', () => {
    const hidden = document.querySelector('.info .visually-hidden');
    expect(hidden.textContent).toContain('On the table:');
  });

  test('a page with no definitions on it does not throw', () => {
    document.body.innerHTML = '<main><p>nothing here</p></main>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// Head to head
// ---------------------------------------------------------------------------
describe('the head-to-head grid', () => {
  const heatMarkup = () => {
    document.body.innerHTML = `
      <main>
        <svg class="heat">
          <text class="heat-head heat-col" data-c="0" data-win="30">Brian</text>
          <text class="heat-head heat-col" data-c="1" data-win="20">Eric</text>
          <text class="heat-head heat-row" data-r="0" data-win="30">Brian</text>
          <text class="heat-head heat-row" data-r="1" data-win="20">Eric</text>
          <rect class="heat-box" data-r="0" data-c="1" data-p="62"
                data-row="Brian Moore" data-col="Eric Riggs"></rect>
          <rect class="heat-box" data-r="1" data-c="0" data-p="38"
                data-row="Eric Riggs" data-col="Brian Moore"></rect>
        </svg>
        <p class="heat-readout" data-heat-readout>Point at any cell.</p>
      </main>`;
  };

  beforeEach(() => {
    heatMarkup();
    init(document, fakeWindow());
  });

  test('a cell reads as a sentence, which is what a bare 62% never did', () => {
    const out = headToHeadReadout({
      row: 'Brian', col: 'Eric', percent: '62', reverse: '38',
      rowWin: '30', colWin: '20',
    });
    expect(out.claim).toBe(
      'Brian finishes above Eric in 62% of simulated seasons, '
      + 'and below them in the other 38%.',
    );
    // One number in isolation misleads: beating somebody 62% of the time reads
    // very differently when neither of you is likely to win the thing.
    expect(out.odds).toBe(
      'Outright, Brian wins the pool 30% of the time and Eric 20%.',
    );
  });

  test('the reverse comes from the opposite cell, not from 100 minus this one', () => {
    // Then the sentence always agrees with the number printed over there,
    // however either of them was rounded.
    expect(headToHeadReadout({
      row: 'A', col: 'B', percent: '62', reverse: '39',
    }).claim).toContain('the other 39%');
  });

  test('without the reverse cell it falls back to the complement', () => {
    expect(headToHeadReadout({ row: 'A', col: 'B', percent: '62' }).claim)
      .toContain('the other 38%');
  });

  test('a grid with no outright odds states the claim and invents nothing', () => {
    const out = headToHeadReadout({ row: 'A', col: 'B', percent: '62', reverse: '38' });
    expect(out.claim).toBeTruthy();
    expect(out.odds).toBeNull();
  });

  test('identical picks are a tie, not two opposing 50% chances', () => {
    const out = headToHeadReadout({
      row: 'Brian', col: 'Zac + Sammy #1', percent: '50', reverse: '50',
      rowWin: '12', colWin: '12', samePicks: true,
    });
    expect(out.claim).toBe(
      'Brian and Zac + Sammy #1 tie in every simulated season because they have the same picks.',
    );
    expect(out.odds).toBeNull();
  });

  test('the grid passes its identical-picks marker into the readout', () => {
    const cell = document.querySelector('[data-r="0"][data-c="1"]');
    cell.dataset.samePicks = 'true';
    cell.dispatchEvent(new window.Event('pointerenter'));

    expect(document.querySelector('[data-heat-readout] .heat-claim').textContent)
      .toBe('Brian Moore and Eric Riggs tie in every simulated season because they have the same picks.');
    expect(document.querySelector('[data-heat-readout] .heat-odds')).toBeNull();
  });

  test('pointing at a cell writes the pair out in full names, with the odds', () => {
    document.querySelector('[data-r="0"][data-c="1"]')
      .dispatchEvent(new window.Event('pointerenter'));

    const readout = document.querySelector('[data-heat-readout]');
    expect(readout.querySelector('.heat-claim').textContent).toBe(
      'Brian Moore finishes above Eric Riggs in 62% of simulated seasons, '
      + 'and below them in the other 38%.',
    );
    expect(readout.querySelector('.heat-odds').textContent).toBe(
      'Outright, Brian Moore wins the pool 30% of the time and Eric Riggs 20%.',
    );
  });

  test('moving to another cell replaces the readout rather than appending to it', () => {
    const cell = (r, c) => document.querySelector(`[data-r="${r}"][data-c="${c}"]`);
    cell(0, 1).dispatchEvent(new window.Event('pointerenter'));
    cell(1, 0).dispatchEvent(new window.Event('pointerenter'));

    const readout = document.querySelector('[data-heat-readout]');
    expect(readout.querySelectorAll('.heat-claim')).toHaveLength(1);
    expect(readout.querySelector('.heat-claim').textContent).toContain(
      'Eric Riggs finishes above Brian Moore in 38%',
    );
  });

  test('the row and the column light up, and only they do', () => {
    document.querySelector('[data-r="0"][data-c="1"]')
      .dispatchEvent(new window.Event('pointerenter'));

    const lit = Array.from(document.querySelectorAll('.is-lit'));
    expect(lit.map((el) => el.textContent).filter(Boolean).sort())
      .toEqual(['Brian', 'Eric']);
    expect(document.querySelectorAll('.is-picked')).toHaveLength(1);
  });

  test('leaving the chart puts the prompt back', () => {
    const chart = document.querySelector('svg.heat');
    chart.querySelector('.heat-box').dispatchEvent(new window.Event('pointerenter'));
    chart.dispatchEvent(new window.Event('pointerleave'));

    expect(document.querySelectorAll('.is-lit')).toHaveLength(0);
    expect(document.querySelector('[data-heat-readout]').textContent)
      .toBe('Point at any cell.');
  });

  // On touch there is no hover to lean on: pointerenter, click and
  // pointerleave all arrive inside the one tap, so anything hover-only is a
  // flash the reader never sees. A tap pins the pair instead.
  test('a tap pins the pair, so the pointer leaving no longer clears it', () => {
    const chart = document.querySelector('svg.heat');
    const cell = document.querySelector('[data-r="0"][data-c="1"]');
    cell.dispatchEvent(new window.Event('pointerenter'));
    cell.dispatchEvent(new window.Event('click', { bubbles: true }));
    chart.dispatchEvent(new window.Event('pointerleave'));

    expect(chart.classList.contains('has-pick')).toBe(true);
    expect(document.querySelectorAll('.is-picked')).toHaveLength(1);
    const readout = document.querySelector('[data-heat-readout]');
    expect(readout.classList.contains('is-live')).toBe(true);
    expect(readout.querySelector('.heat-claim').textContent)
      .toContain('Brian Moore finishes above Eric Riggs');
  });

  test('while a pair is held, the pointer passing over other cells does not steal it', () => {
    const cell = (r, c) => document.querySelector(`[data-r="${r}"][data-c="${c}"]`);
    cell(0, 1).dispatchEvent(new window.Event('click', { bubbles: true }));
    cell(1, 0).dispatchEvent(new window.Event('pointerenter'));

    expect(document.querySelector('[data-heat-readout] .heat-claim').textContent)
      .toContain('Brian Moore finishes above Eric Riggs');
  });

  test('tapping the held cell again lets it go', () => {
    const cell = document.querySelector('[data-r="0"][data-c="1"]');
    cell.dispatchEvent(new window.Event('click', { bubbles: true }));
    cell.dispatchEvent(new window.Event('click', { bubbles: true }));

    expect(document.querySelectorAll('.is-picked')).toHaveLength(0);
    expect(document.querySelector('svg.heat').classList.contains('has-pick')).toBe(false);
    expect(document.querySelector('[data-heat-readout]').textContent)
      .toBe('Point at any cell.');
  });

  test('tapping another cell moves the hold rather than stacking it', () => {
    const cell = (r, c) => document.querySelector(`[data-r="${r}"][data-c="${c}"]`);
    cell(0, 1).dispatchEvent(new window.Event('click', { bubbles: true }));
    cell(1, 0).dispatchEvent(new window.Event('click', { bubbles: true }));

    expect(document.querySelectorAll('.is-picked')).toHaveLength(1);
    expect(document.querySelector('[data-heat-readout] .heat-claim').textContent)
      .toContain('Eric Riggs finishes above Brian Moore in 38%');
  });

  test('tapping away from the grid lets the pair go', () => {
    document.querySelector('[data-r="0"][data-c="1"]')
      .dispatchEvent(new window.Event('click', { bubbles: true }));
    document.body.dispatchEvent(new window.Event('click', { bubbles: true }));

    expect(document.querySelectorAll('.is-picked')).toHaveLength(0);
    expect(document.querySelector('[data-heat-readout]').textContent)
      .toBe('Point at any cell.');
  });

  test('Escape lets the pair go, like every other held thing', () => {
    document.querySelector('[data-r="0"][data-c="1"]')
      .dispatchEvent(new window.Event('click', { bubbles: true }));
    document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' }));

    expect(document.querySelectorAll('.is-picked')).toHaveLength(0);
    expect(document.querySelector('[data-heat-readout]').textContent)
      .toBe('Point at any cell.');
  });

  test('a page with no grid on it does not throw', () => {
    document.body.innerHTML = '<main><p>nothing here</p></main>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});

describe('the money grid, and the picker over the two', () => {
  /**
   * Both grids as the forecast page ships them: the finishing one shown, the
   * money one hidden, one note each, and a select over the pair.
   */
  const bothGrids = () => {
    const grid = (view, ab, ba, rowWin, colWin) => `
      <div class="table-scroll" data-heat-grid="${view}"${view === 'money' ? ' hidden' : ''}>
        <svg class="heat">
          <text class="heat-head heat-col" data-c="0" data-win="${rowWin}">Brian</text>
          <text class="heat-head heat-col" data-c="1" data-win="${colWin}">Eric</text>
          <text class="heat-head heat-row" data-r="0" data-win="${rowWin}">Brian</text>
          <text class="heat-head heat-row" data-r="1" data-win="${colWin}">Eric</text>
          <rect class="heat-box" data-r="0" data-c="1" data-p="${ab}"
                data-row="Brian Moore" data-col="Eric Riggs"></rect>
          <rect class="heat-box" data-r="1" data-c="0" data-p="${ba}"
                data-row="Eric Riggs" data-col="Brian Moore"></rect>
        </svg>
      </div>`;

    document.body.innerHTML = `
      <main>
        <label><select data-heat-view>
          <option value="order">Who finishes above whom</option>
          <option value="money">Who out-earns whom</option>
        </select></label>
        <div class="heat-wrap" data-heat-wrap>
          <p data-heat-note="order">Opposite cells add to 100%.</p>
          <p data-heat-note="money" hidden>Or to less than 100%.</p>
          ${grid('order', 62, 38, 30, 20)}
          ${grid('money', 41, 27, 70, 55)}
          <p class="heat-readout" data-heat-readout>Point at any cell.</p>
        </div>
      </main>`;
  };

  const pick = (view) => {
    const select = document.querySelector('[data-heat-view]');
    select.value = view;
    select.dispatchEvent(new window.Event('change'));
  };
  const shown = () => Array.from(document.querySelectorAll('[data-heat-grid]'))
    .filter((g) => !g.hidden).map((g) => g.dataset.heatGrid);

  beforeEach(() => {
    bothGrids();
    init(document, fakeWindow());
  });

  test('the money sentence names the seasons that paid them the same', () => {
    // 41 and 27 leaves 32% where neither took more than the other — a gap the
    // finishing grid never has, and one a reader would otherwise have to
    // notice and explain to themselves.
    const out = headToHeadReadout({
      row: 'Brian', col: 'Eric', percent: '41', reverse: '27',
      rowWin: '70', colWin: '55', view: 'money',
    });
    expect(out.claim).toBe(
      'Brian takes home more than Eric in 41% of simulated seasons, '
      + 'less in 27%, and the same in the other 32%.',
    );
    expect(out.odds).toBe(
      'Outright, Brian is paid something 70% of the time and Eric 55%.',
    );
  });

  test('no ties, no clause about them', () => {
    expect(headToHeadReadout({
      row: 'A', col: 'B', percent: '78', reverse: '22', view: 'money',
    }).claim).toBe(
      'A takes home more than B in 78% of simulated seasons, less in 22%.',
    );
  });

  test('a rounding overshoot never reports a negative share of ties', () => {
    expect(headToHeadReadout({
      row: 'A', col: 'B', percent: '51', reverse: '50', view: 'money',
    }).claim).not.toContain('-');
  });

  test('the picker swaps the grid, the note, and nothing else', () => {
    expect(shown()).toEqual(['order']);

    pick('money');
    expect(shown()).toEqual(['money']);
    expect(document.querySelector('[data-heat-note="money"]').hidden).toBe(false);
    expect(document.querySelector('[data-heat-note="order"]').hidden).toBe(true);

    pick('order');
    expect(shown()).toEqual(['order']);
    expect(document.querySelector('[data-heat-note="order"]').hidden).toBe(false);
  });

  test('each grid reads its own cells in its own words', () => {
    const cell = (view, r, c) => document.querySelector(
      `[data-heat-grid="${view}"] .heat-box[data-r="${r}"][data-c="${c}"]`,
    );
    const readout = document.querySelector('[data-heat-readout]');

    cell('order', 0, 1).dispatchEvent(new window.Event('pointerenter'));
    expect(readout.querySelector('.heat-claim').textContent)
      .toContain('finishes above Eric Riggs in 62%');
    expect(readout.querySelector('.heat-odds').textContent)
      .toContain('wins the pool 30%');

    pick('money');
    cell('money', 0, 1).dispatchEvent(new window.Event('pointerenter'));
    expect(readout.querySelector('.heat-claim').textContent)
      .toBe('Brian Moore takes home more than Eric Riggs in 41% of simulated '
        + 'seasons, less in 27%, and the same in the other 32%.');
    expect(readout.querySelector('.heat-odds').textContent)
      .toContain('is paid something 70%');
  });

  test('switching clears a readout describing a cell that has left the screen', () => {
    document.querySelector('[data-heat-grid="order"] .heat-box')
      .dispatchEvent(new window.Event('pointerenter'));
    pick('money');
    expect(document.querySelector('[data-heat-readout]').textContent)
      .toBe('Point at any cell.');
  });

  test('switching lets a pinned pair go with the grid it was pinned in', () => {
    document.querySelector('[data-heat-grid="order"] .heat-box')
      .dispatchEvent(new window.Event('click', { bubbles: true }));
    pick('money');

    expect(document.querySelectorAll('.is-picked')).toHaveLength(0);
    expect(document.querySelectorAll('svg.heat.has-pick')).toHaveLength(0);
    expect(document.querySelector('[data-heat-readout]').textContent)
      .toBe('Point at any cell.');

    // And the freed grid is back on hover, not stuck behind a stale pin.
    document.querySelector('[data-heat-grid="money"] .heat-box')
      .dispatchEvent(new window.Event('pointerenter'));
    expect(document.querySelector('[data-heat-readout] .heat-claim').textContent)
      .toContain('takes home more');
  });

  test('the select is pulled into line with the markup, not the other way round', () => {
    // A browser restoring a stale selection must not leave the page showing
    // one grid and naming the other.
    bothGrids();
    document.querySelector('[data-heat-view]').value = 'money';
    init(document, fakeWindow());

    expect(document.querySelector('[data-heat-view]').value).toBe('order');
    expect(shown()).toEqual(['order']);
  });

  test('a page with the picker but no grids is left alone', () => {
    document.body.innerHTML = '<main><select data-heat-view></select></main>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------
describe('firstSortDirection', () => {
  const heading = (html) => {
    document.body.innerHTML = `<table><thead><tr>${html}</tr></thead></table>`;
    return document.querySelector('th');
  };

  test('numbers open biggest-first and names open A-Z', () => {
    expect(firstSortDirection(heading('<th class="num" data-sort>Points</th>'))).toBe(-1);
    expect(firstSortDirection(heading('<th data-sort>Entrant</th>'))).toBe(1);
  });

  test('a column where small is good says so, and is believed', () => {
    // Rank and "behind the leader" are numbers where first place is the
    // smallest value, so the num heuristic is exactly wrong for them.
    expect(firstSortDirection(heading('<th class="num" data-sort="ascending">Rank</th>'))).toBe(1);
    expect(firstSortDirection(heading('<th data-sort="descending">Share</th>'))).toBe(-1);
  });
});

describe('a table the server already sorted', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table>
        <thead><tr>
          <th data-sort>Entrant</th>
          <th class="num" data-sort aria-sort="descending">Expected payout</th>
        </tr></thead>
        <tbody>
          <tr><th>Brian</th><td class="num" data-value="40">$40</td></tr>
          <tr><th>Eric</th><td class="num" data-value="12">$12</td></tr>
        </tbody>
      </table>`;
    init(document, fakeWindow());
  });

  const names = () =>
    Array.from(document.querySelectorAll('tbody tr th')).map((el) => el.textContent);

  test('the first click reverses it rather than re-sorting to what is on screen', () => {
    document.querySelectorAll('th')[1].dispatchEvent(new window.Event('click'));

    expect(names()).toEqual(['Eric', 'Brian']);
    expect(document.querySelectorAll('th')[1].getAttribute('aria-sort')).toBe('ascending');
  });
});

// ---------------------------------------------------------------------------
// Arriving
// ---------------------------------------------------------------------------
describe('reveal on scroll', () => {
  const revealMarkup = () => {
    document.body.innerHTML = `
      <main>
        <div class="stat">one</div>
        <div class="card">two</div>
        <p>not a block</p>
      </main>`;
  };

  beforeEach(revealMarkup);

  test('the hidden state is added by the client, never by the stylesheet', () => {
    // With scripting off nothing is hidden, which is why this is safe at all.
    expect(document.querySelectorAll('.will-reveal')).toHaveLength(0);

    init(document, fakeWindow());
    expect(document.querySelectorAll('.will-reveal')).toHaveLength(2);
    expect(REVEAL_SELECTOR).toContain('.stat');
    // Headings and copy are deliberately not in it — see the export.
    expect(REVEAL_SELECTOR).not.toContain('.section-title');
  });

  test('a block that arrives is revealed once and then let go of', () => {
    const win = fakeWindow();
    init(document, win);

    const [observer] = win._observers;
    const stat = document.querySelector('.stat');
    observer.callback([{ target: stat, isIntersecting: true }]);

    expect(stat.classList.contains('will-reveal')).toBe(false);
    expect(observer.targets).not.toContain(stat);
  });

  test('a block still off screen stays hidden and stays watched', () => {
    const win = fakeWindow();
    init(document, win);

    const [observer] = win._observers;
    const card = document.querySelector('.card');
    observer.callback([{ target: card, isIntersecting: false }]);

    expect(card.classList.contains('will-reveal')).toBe(true);
    expect(observer.targets).toContain(card);
  });

  test('nothing is hidden when the reader has asked for less motion', () => {
    init(document, fakeWindow({ reduceMotion: true }));
    expect(document.querySelectorAll('.will-reveal')).toHaveLength(0);
  });

  test('a browser with no observer leaves the page exactly as it was', () => {
    const win = fakeWindow();
    win.IntersectionObserver = undefined;
    init(document, win);
    expect(document.querySelectorAll('.will-reveal')).toHaveLength(0);
  });

  test('a block already on screen is left visible — there is nothing to arrive', () => {
    // This module is deferred, so on a slow connection the first screen can be
    // painted before it runs. Hiding what the reader is already looking at
    // would be a flicker rather than an entrance.
    const stat = document.querySelector('.stat');
    const card = document.querySelector('.card');
    stat.getBoundingClientRect = () => ({ top: 120, width: 300, height: 90 });
    card.getBoundingClientRect = () => ({ top: 1400, width: 300, height: 90 });

    init(document, fakeWindow({ innerHeight: 900 }));

    expect(stat.classList.contains('will-reveal')).toBe(false);
    expect(card.classList.contains('will-reveal')).toBe(true);
  });

  test('a block the page is already hiding is never hidden a second time', () => {
    // The schedule shows one week and hides the rest in CSS. Hiding those
    // again would leave a week you switch to blank until the observer got
    // round to it — or for good, if it never did.
    const card = document.querySelector('.card');
    card.checkVisibility = () => false;
    document.querySelector('.stat').checkVisibility = () => true;

    init(document, fakeWindow());

    expect(card.classList.contains('will-reveal')).toBe(false);
    expect(document.querySelector('.stat').classList.contains('will-reveal')).toBe(true);
  });
});

describe('the field on a page that cannot draw', () => {
  test('no 2D context means no field, and no error either', () => {
    document.body.innerHTML = '<canvas class="gridiron" data-near="Family Pool"></canvas>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});

describe('the chain crew', () => {
  const chains = () =>
    '<div class="drive"><div class="drive-line"><span class="drive-yard"></span></div></div>';

  /** A page long enough to have somewhere to drive to. */
  const scrollable = (height = 4000) => {
    Object.defineProperty(document.documentElement, 'scrollHeight', {
      value: height, configurable: true,
    });
  };

  test('the page reports how far down it is, and never further', () => {
    expect(scrollProgress(0, 1000)).toBe(0);
    expect(scrollProgress(500, 1000)).toBe(0.5);
    expect(scrollProgress(1200, 1000)).toBe(1);
    expect(scrollProgress(-50, 1000)).toBe(0);
  });

  test('a page with nowhere to scroll is at the start, not divided by zero', () => {
    expect(scrollProgress(0, 0)).toBe(0);
    expect(scrollProgress(10, -40)).toBe(0);
  });

  test('a spot on the field reads the way a commentator says it', () => {
    expect(driveLabel(0)).toBe('Own goal line');
    expect(driveLabel(25)).toBe('Own 25');
    expect(driveLabel(50)).toBe('Midfield');
    expect(driveLabel(88)).toBe('Opp 12');
    expect(driveLabel(100)).toBe('Touchdown');
  });

  test('the marks sit out when the reader has asked for less motion', () => {
    document.body.innerHTML = chains();
    init(document, fakeWindow({ reduceMotion: true }));

    expect(document.querySelector('.drive-line').style.transform).toBe('');
  });

  test('the marks start on the goal line and report a page with nowhere to go', () => {
    document.body.innerHTML = chains();
    init(document, fakeWindow({ innerHeight: 900 }));

    // jsdom lays nothing out, so scrollHeight is zero: no scroll, no drive.
    expect(document.querySelector('.drive').classList.contains('is-live')).toBe(false);
    expect(document.querySelector('.drive-yard').textContent).toBe('Own goal line');
    expect(document.querySelector('.drive-line').style.transform)
      .toBe('translate3d(0, 75.0px, 0)');
  });

  test('the yard label waits until the drive has left its own goal line', () => {
    // On the goal line the marks sit under the masthead, which would put the
    // label in the viewer bar and cut it in half.
    document.body.innerHTML = chains();
    scrollable();

    const win = fakeWindow({ innerHeight: 900, scrollY: 0 });
    init(document, win);
    const drive = document.querySelector('.drive');
    expect(drive.classList.contains('is-live')).toBe(true);
    expect(drive.classList.contains('is-moving')).toBe(false);

    win.scrollY = 1550; // half way down a 3100px scroll
    win._fire('scroll');
    win._frames.pop()();

    expect(drive.classList.contains('is-moving')).toBe(true);
    expect(document.querySelector('.drive-yard').textContent).toBe('Midfield');
  });

  test('inside the twenty the chains change colour, and only there', () => {
    document.body.innerHTML = chains();
    scrollable();

    const win = fakeWindow({ innerHeight: 900, scrollY: 0 });
    init(document, win);
    const drive = document.querySelector('.drive');
    expect(drive.classList.contains('is-redzone')).toBe(false);

    // 85 yards down the field: inside the twenty, not yet over the line.
    win.scrollY = 3100 * (RED_ZONE + 5) / 100;
    win._fire('scroll');
    win._frames.pop()();

    expect(drive.classList.contains('is-redzone')).toBe(true);
    expect(drive.classList.contains('is-td')).toBe(false);
    expect(document.querySelector('.drive-yard').textContent).toBe('Opp 15');
  });

  test('the bottom of the page is a touchdown, and scrolling back takes it away', () => {
    document.body.innerHTML = chains();
    scrollable();

    const win = fakeWindow({ innerHeight: 900, scrollY: 3100 });
    init(document, win);
    const drive = document.querySelector('.drive');
    expect(drive.classList.contains('is-td')).toBe(true);
    expect(document.querySelector('.drive-yard').textContent).toBe('Touchdown');

    win.scrollY = 1000;
    win._fire('scroll');
    win._frames.pop()();
    expect(drive.classList.contains('is-td')).toBe(false);
  });

  test('one frame per flick, however many scroll events arrive', () => {
    document.body.innerHTML = chains();
    scrollable();
    const win = fakeWindow({ innerHeight: 900 });
    init(document, win);
    win._frames.length = 0;

    win._fire('scroll');
    win._fire('scroll');
    win._fire('scroll');
    expect(win._frames.length).toBe(1);

    // Once the frame has run, the next flick may ask for another.
    win._frames.pop()();
    win._fire('scroll');
    expect(win._frames.length).toBe(1);
  });

  test('a page without the markup is not a problem', () => {
    document.body.innerHTML = '<p>no field here</p>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});

describe('the floodlight wipe', () => {
  /** The distance to the far corner, from a few places on the screen. */
  test('the circle reaches the furthest corner, wherever it starts', () => {
    const viewport = { width: 300, height: 400 };
    expect(sweepRadius({ x: 0, y: 0 }, viewport)).toBe(500);
    expect(sweepRadius({ x: 300, y: 400 }, viewport)).toBe(500);
    // Dead centre is the only place where every corner is the same distance.
    expect(sweepRadius({ x: 150, y: 200 }, viewport)).toBeCloseTo(250, 6);
  });

  test('a browser with view transitions wipes the new palette in', async () => {
    markup();
    const win = fakeWindow();
    let captured = null;
    document.startViewTransition = (apply) => {
      captured = document.documentElement.className;
      apply();
      return { finished: Promise.resolve() };
    };

    try {
      init(document, win);
      document.querySelector('[data-theme-toggle]').click();

      // The class has to be on before the old state is captured, or the
      // stylesheet's wipe never applies to this transition.
      expect(captured).toContain('is-relighting');
      expect(document.documentElement.dataset.theme).toBe('light');
      expect(win._store.get(THEME_KEY)).toBe('light');

      // jsdom puts the button at the origin, so the circle has to cover the
      // whole 1280 × 900 viewport from its top-left corner.
      const root = document.documentElement.style;
      expect(root.getPropertyValue('--sweep-x')).toBe('0.0px');
      expect(root.getPropertyValue('--sweep-y')).toBe('0.0px');
      expect(root.getPropertyValue('--sweep-r')).toBe(`${Math.hypot(1280, 900).toFixed(1)}px`);

      // And off again once the wipe has finished, so a page-to-page morph is
      // never dressed up as a change of theme.
      await Promise.resolve();
      await Promise.resolve();
      expect(document.documentElement.classList.contains('is-relighting')).toBe(false);
    } finally {
      delete document.startViewTransition;
    }
  });

  test('a transition that is abandoned still tidies up after itself', async () => {
    markup();
    document.startViewTransition = (apply) => {
      apply();
      return { finished: Promise.reject(new Error('skipped')) };
    };

    try {
      init(document, fakeWindow());
      document.querySelector('[data-theme-toggle]').click();
      await Promise.resolve();
      await Promise.resolve();
      expect(document.documentElement.classList.contains('is-relighting')).toBe(false);
    } finally {
      delete document.startViewTransition;
    }
  });

  test('less motion means the theme simply changes', () => {
    markup();
    const started = vi.fn();
    document.startViewTransition = started;

    try {
      init(document, fakeWindow({ reduceMotion: true }));
      document.querySelector('[data-theme-toggle]').click();
      expect(started).not.toHaveBeenCalled();
      expect(document.documentElement.dataset.theme).toBe('light');
      expect(document.documentElement.classList.contains('is-relighting')).toBe(false);
    } finally {
      delete document.startViewTransition;
    }
  });
});

describe('rows gliding to their new places', () => {
  test('only the rows that actually moved, and only by how far', () => {
    const a = {}; const b = {}; const gone = {};
    const before = new Map([[a, 0], [b, 40], [gone, 80]]);
    const after = new Map([[b, 0], [a, 40], [{}, 80]]);

    expect(flipShifts(before, after)).toEqual([{ row: b, dy: 40 }, { row: a, dy: -40 }]);
  });

  test('sub-pixel drift is not movement', () => {
    const row = {};
    expect(flipShifts(new Map([[row, 10]]), new Map([[row, 10.4]]))).toEqual([]);
  });

  test('a table with no body has no rows to read', () => {
    document.body.innerHTML = '<table></table>';
    expect(rowTops(document.querySelector('table')).size).toBe(0);
  });

  test('sorting sends every row that moved back to where it was', () => {
    document.body.innerHTML = `
      <table>
        <thead><tr><th data-sort>Team</th><th data-sort class="num">Points</th></tr></thead>
        <tbody>
          <tr><th data-value="ARI">ARI</th><td data-value="4">4.00</td></tr>
          <tr><th data-value="KC">KC</th><td data-value="30">30.00</td></tr>
          <tr><th data-value="DAL">DAL</th><td data-value="12">12.00</td></tr>
        </tbody>
      </table>`;

    // jsdom lays nothing out, so each row reports the place it is standing in.
    const rows = [...document.querySelectorAll('tbody tr')];
    const plays = [];
    for (const row of rows) {
      row.getBoundingClientRect = () => ({
        top: [...row.parentElement.rows].indexOf(row) * 40,
      });
      row.animate = (frames, options) => plays.push({ row, frames, options });
    }

    init(document, fakeWindow());
    document.querySelectorAll('th[data-sort]')[1].click();

    // Biggest first, so KC and DAL each come up a place and ARI drops two —
    // and each one starts from exactly where it was standing.
    expect([...document.querySelectorAll('tbody th')].map((c) => c.textContent))
      .toEqual(['KC', 'DAL', 'ARI']);
    expect(plays.map((p) => p.frames[0].transform))
      .toEqual(['translateY(40.0px)', 'translateY(40.0px)', 'translateY(-80.0px)']);
    expect(plays.every((p) => p.frames[1].transform === 'none')).toBe(true);
    expect(plays[0].options.duration).toBe(420);
  });

  test('less motion means the rows are simply where they belong', () => {
    document.body.innerHTML = `
      <table>
        <thead><tr><th data-sort class="num">Points</th></tr></thead>
        <tbody>
          <tr><td data-value="4">4.00</td></tr>
          <tr><td data-value="30">30.00</td></tr>
        </tbody>
      </table>`;
    const played = vi.fn();
    for (const row of document.querySelectorAll('tbody tr')) {
      row.getBoundingClientRect = () => ({
        top: [...row.parentElement.rows].indexOf(row) * 40,
      });
      row.animate = played;
    }

    init(document, fakeWindow({ reduceMotion: true }));
    document.querySelector('th[data-sort]').click();

    expect([...document.querySelectorAll('td')].map((c) => c.textContent))
      .toEqual(['30.00', '4.00']);
    expect(played).not.toHaveBeenCalled();
  });

  test('a browser without the animation API sorts anyway', () => {
    document.body.innerHTML = `
      <table>
        <thead><tr><th data-sort class="num">Points</th></tr></thead>
        <tbody>
          <tr><td data-value="4">4.00</td></tr>
          <tr><td data-value="30">30.00</td></tr>
        </tbody>
      </table>`;
    for (const row of document.querySelectorAll('tbody tr')) {
      row.getBoundingClientRect = () => ({
        top: [...row.parentElement.rows].indexOf(row) * 40,
      });
    }

    init(document, fakeWindow());
    expect(() => document.querySelector('th[data-sort]').click()).not.toThrow();
    expect([...document.querySelectorAll('td')].map((c) => c.textContent))
      .toEqual(['30.00', '4.00']);
  });
});

describe('the field on a page that can draw', () => {
  /** Put a canvas on the page whose context records rather than renders. */
  const paintable = () => {
    document.body.innerHTML =
      '<canvas class="gridiron" data-near="Family Pool" data-far="2026"></canvas>';
    const canvas = document.querySelector('canvas');
    const ctx = recordingContext();
    canvas.getContext = () => ctx;
    return { canvas, ctx };
  };

  test('the bitmap is sized for the device, so the chalk lines are not fuzzy', () => {
    const { canvas } = paintable();
    init(document, fakeWindow({ innerWidth: 400, innerHeight: 850 }));

    // Twice the CSS size at devicePixelRatio 2, with the context scaled to
    // match so the drawing code still works in CSS pixels.
    expect(canvas.width).toBe(800);
    expect(canvas.height).toBe(1700);
  });

  test('the whole field is painted on first sight', () => {
    const { ctx } = paintable();
    init(document, fakeWindow());

    expect(ctx.calls.some((c) => c.name === 'clearRect')).toBe(true);
    const words = ctx.calls.filter((c) => c.name === 'fillText').map((c) => c.args[0]);
    expect(words).toContain('FAMILY POOL');
    expect(words).toContain('2026');
  });

  test('switching the theme repaints it, because every colour hangs off that', () => {
    const { ctx } = paintable();
    const win = fakeWindow();
    init(document, win);

    const first = ctx.calls.length;
    const watcher = win._observers.find((o) => typeof o.observe === 'function' && !o.targets);
    watcher.callback();

    expect(ctx.calls.length).toBeGreaterThan(first);
  });

  test('a resize wider repaints; an address bar sliding away does not', () => {
    const { ctx } = paintable();
    const win = fakeWindow({ innerWidth: 400, innerHeight: 850 });
    init(document, win);

    const painted = ctx.calls.length;

    // The phone case: the browser chrome hides and the viewport grows by 60px.
    // Repainting the entire field for that would flicker on every scroll.
    win.innerHeight = 910;
    win._fire('resize');
    expect(ctx.calls.length).toBe(painted);

    // A genuine change of width always counts.
    win.innerWidth = 900;
    win._fire('resize');
    expect(ctx.calls.length).toBeGreaterThan(painted);
  });

  test('a real change of height counts too — a rotated phone, a resized window', () => {
    const { ctx } = paintable();
    const win = fakeWindow({ innerWidth: 400, innerHeight: 850 });
    init(document, win);

    const painted = ctx.calls.length;
    win.innerHeight = 400;
    win._fire('resize');
    expect(ctx.calls.length).toBeGreaterThan(painted);
  });
});

describe('a definition button inside a sortable heading', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <main>
        <table>
          <thead><tr>
            <th data-sort>Entrant</th>
            <th class="num" data-sort>Expected payout<span class="term">
              <button class="info" type="button" aria-expanded="false"></button>
              <span class="def"></span>
            </span></th>
          </tr></thead>
          <tbody>
            <tr><th>Brian</th><td class="num" data-value="40">$40</td></tr>
            <tr><th>Eric</th><td class="num" data-value="12">$12</td></tr>
          </tbody>
        </table>
      </main>`;
    for (const el of document.querySelectorAll('.info, .def')) {
      el.getBoundingClientRect = () => ({
        top: 10, left: 20, bottom: 25, width: 15, height: 15,
      });
    }
    init(document, fakeWindow());
  });

  const names = () =>
    Array.from(document.querySelectorAll('tbody tr th')).map((el) => el.textContent);

  test('the sort tooltip omits the definition hidden inside the heading', () => {
    expect(document.querySelectorAll('th')[1].title)
      .toBe('Sort by Expected payout, descending');
  });

  test('asking what a column means does not reorder the table underneath', () => {
    const before = names();
    document.querySelector('.info')
      .dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

    expect(document.querySelector('.term').classList.contains('is-open')).toBe(true);
    expect(names()).toEqual(before);
    expect(document.querySelectorAll('th')[1].getAttribute('aria-sort')).toBeNull();
  });

  test('the heading itself still sorts', () => {
    document.querySelectorAll('th')[1]
      .dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(names()).toEqual(['Brian', 'Eric']);
  });

  test('activating the button by keyboard does not sort either', () => {
    document.querySelector('.info').dispatchEvent(
      new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
    );
    expect(document.querySelectorAll('th')[1].getAttribute('aria-sort')).toBeNull();
  });
});

describe('tracing a team through the playoffs', () => {
  const bracketMarkup = () => {
    document.body.innerHTML = `
      <div class="bracket" data-bracket>
        <div class="tie" data-tie="WC">
          <div class="tie-side" data-team="LAC"><a class="team-chip" href="/team/LAC/">LAC</a></div>
          <div class="tie-side" data-team="NE"><a class="team-chip" href="/team/NE/">NE</a>
            <span class="owners"><a class="owner" href="/entrant/carol/">Carol</a></span></div>
        </div>
        <div class="tie" data-tie="DIV">
          <div class="tie-side" data-team="NE"><a class="team-chip" href="/team/NE/">NE</a></div>
          <div class="tie-side" data-team="DEN"><a class="team-chip" href="/team/DEN/">DEN</a></div>
        </div>
        <div class="tie is-open" data-tie="SB">
          <div class="tie-side"><span class="tie-slot">AFC champion</span></div>
          <div class="tie-side"><span class="tie-slot">NFC champion</span></div>
        </div>
      </div>`;
  };

  beforeEach(bracketMarkup);

  const over = (el) => el.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
  const chipFor = (round, team) =>
    document.querySelector(`.tie[data-tie="${round}"] .tie-side[data-team="${team}"] .team-chip`);

  test('pointing at a team lights every game on its road', () => {
    init(document, fakeWindow());
    over(chipFor('WC', 'NE'));

    const bracket = document.querySelector('[data-bracket]');
    expect(bracket.classList.contains('is-tracing')).toBe(true);
    expect(document.querySelectorAll('.tie-side.is-path')).toHaveLength(2);
    // The whole game comes forward, not half a card — the game is what pays.
    expect(document.querySelector('[data-tie="WC"]').classList.contains('has-path')).toBe(true);
    expect(document.querySelector('[data-tie="DIV"]').classList.contains('has-path')).toBe(true);
    // A slot with no team yet is on nobody's road.
    expect(document.querySelector('[data-tie="SB"]').classList.contains('has-path')).toBe(false);
  });

  test('an owner inside a side traces that side too', () => {
    // The owners sit inside the side, so pointing at a name is pointing at
    // the team it is riding on.
    init(document, fakeWindow());
    over(document.querySelector('.owner'));
    expect(document.querySelectorAll('.tie-side.is-path')).toHaveLength(2);
  });

  test('pointing somewhere that is not a team clears the trace', () => {
    init(document, fakeWindow());
    over(chipFor('WC', 'NE'));
    over(document.querySelector('.tie-slot'));

    expect(document.querySelector('[data-bracket]').classList.contains('is-tracing')).toBe(false);
    expect(document.querySelectorAll('.is-path')).toHaveLength(0);
    expect(document.querySelectorAll('.has-path')).toHaveLength(0);
  });

  test('leaving the bracket clears it too', () => {
    init(document, fakeWindow());
    over(chipFor('DIV', 'DEN'));
    document.querySelector('[data-bracket]')
      .dispatchEvent(new window.MouseEvent('mouseleave'));
    expect(document.querySelectorAll('.is-path')).toHaveLength(0);
  });

  test('keyboard focus walks the same road', () => {
    init(document, fakeWindow());
    const chip = chipFor('WC', 'NE');
    chip.dispatchEvent(new window.FocusEvent('focusin', { bubbles: true }));
    expect(document.querySelectorAll('.tie-side.is-path')).toHaveLength(2);

    chip.dispatchEvent(new window.FocusEvent('focusout', { bubbles: true }));
    expect(document.querySelectorAll('.is-path')).toHaveLength(0);
  });

  test('an empty preseason bracket wires nothing and throws nothing', () => {
    document.body.innerHTML = `
      <div class="bracket" data-bracket>
        <div class="tie is-open" data-tie="WC">
          <div class="tie-side"><span class="tie-slot">2 seed</span></div>
        </div>
      </div>`;
    expect(() => init(document, fakeWindow())).not.toThrow();
  });

  test('a page with no bracket is left alone', () => {
    document.body.innerHTML = '<main><p>standings</p></main>';
    expect(() => init(document, fakeWindow())).not.toThrow();
  });
});
