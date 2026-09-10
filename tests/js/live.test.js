import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { setImmediate } from 'node:timers/promises';
import fixture from '../fixtures/espn_game_summary.json';
import { fetchEspnJson, parseEspnScoreboard, normalizeEspnTeam, formatTimestamp } from '../../assets/site.js';
import { BASELINE_INTERVAL, FAST_LIVE_INTERVAL, LIVE_INTERVAL, WAIT_INTERVAL, chooseLiveGame, initLivePage,
  liveFieldPosition, liveOutcome, livePoolStandings, liveRefreshDelay, liveScoreboardUrl,
  matchLiveGame, parseLiveSummary, validateLiveBaseline } from '../../assets/live.js';

const helpers = { fetchEspnJson, parseEspnScoreboard, normalizeEspnTeam, formatTimestamp };
const clone = (data) => structuredClone(data);
const NOW = Date.parse('2025-09-07T18:30:00Z');
const ID = '401772830';

function seed() {
  return { version: 1, season: 2025, pool: '', generated: '2025-09-07T16:00:00Z',
    entrants: [{ slug: 'alex', name: 'Alex', teams: ['TB'], banked: 10 },
      { slug: 'blair', name: 'Blair', teams: ['ATL'], banked: 10 },
      { slug: 'cam', name: 'Cam', teams: ['TB', 'ATL'], banked: 9 }],
    games: [{ id: '2025_01_TB_ATL', espnId: ID, week: 1, kind: 'REG',
      date: '2025-09-07', kickoff: '2025-09-07T17:00:00Z', away: 'TB', home: 'ATL', scored: false,
      points: { alex: { TB: 2, ATL: 0, TIE: 1 }, blair: { TB: 0, ATL: 3, TIE: 1.5 }, cam: { TB: 2, ATL: 3, TIE: 2.5 } } }],
    windows: [{ key: 'REG-1', label: 'Week 1', week: 1, kind: 'REG', start: '20250907', end: '20250908', closes: '2025-09-09T04:00:00Z' }],
  };
}

function summary(state = 'in', id = ID) {
  const data = clone(fixture);
  data.header.id = id;
  const comp = data.header.competitions[0];
  comp.status = { period: state === 'post' ? 4 : 3, displayClock: '8:12',
    type: { state, completed: state === 'post', name: state === 'in' ? 'STATUS_IN_PROGRESS' : state === 'post' ? 'STATUS_FINAL' : 'STATUS_SCHEDULED', shortDetail: state === 'post' ? 'Final' : '8:12 - 3rd' } };
  comp.competitors.find((c) => c.homeAway === 'away').score = '21';
  comp.competitors.find((c) => c.homeAway === 'home').score = '17';
  return data;
}
function scoreboard(data = summary()) {
  const h = clone(data.header);
  const comp = h.competitions[0];
  comp.situation = { possession: comp.competitors.find((c) => c.homeAway === 'away').id,
    downDistanceText: '2nd & 8 at ATL 20', distance: 8, isRedZone: true };
  return { events: [{ ...h, date: comp.date, status: comp.status }] };
}
const game = (changes = {}) => ({ ...parseEspnScoreboard(scoreboard())[0], ...changes });

describe('Live feed and scoring contracts', () => {
  test('accepts a baseline and rejects incomplete or ambiguous scoring inputs', () => {
    expect(validateLiveBaseline(seed()).season).toBe(2025);
    for (const mutate of [
      (d) => { d.version = 2; }, (d) => { d.entrants = []; },
      (d) => { d.entrants[0].banked = NaN; }, (d) => { d.games[0].espnId = '401.0'; },
      (d) => { delete d.games[0].points.alex.TIE; },
      (d) => { d.games.push(clone(d.games[0])); },
      (d) => { d.entrants.push(clone(d.entrants[0])); },
      (d) => { d.windows[0].closes = 'bad'; },
    ]) { const d = seed(); mutate(d); expect(() => validateLiveBaseline(d)).toThrow(); }
    expect(() => validateLiveBaseline(null)).toThrow();
    const completed = seed(); completed.games[0].scored = true; completed.games[0].points = {};
    expect(validateLiveBaseline(completed)).toBe(completed);
  });

  test('prefers IDs, matches legacy dates/weeks, and never guesses across seasons', () => {
    const g = seed().games[0]; const e = game();
    expect(matchLiveGame(g, [e], 2025)).toBe(e);
    expect(matchLiveGame({ ...g, espnId: '' }, [e], 2025)).toBe(e);
    expect(matchLiveGame(g, [{ ...e, date: '2025-09-08T17:00Z' }], 2025)).toBeTruthy();
    expect(matchLiveGame(g, [{ ...e, seasonYear: 2026 }], 2025)).toBeNull();
    expect(matchLiveGame({ ...g, espnId: '' }, [e, { ...e, id: '999' }], 2025)).toBeNull();
    expect(matchLiveGame({ ...g, espnId: '', week: 2 }, [{ ...e, date: '', week: 3 }], 2025)).toBeNull();
    expect(matchLiveGame({ ...g, kind: 'SB', espnId: '', week: 22 }, [{ ...e, seasonType: 3, week: 5, date: '' }], 2025)).toBeTruthy();
  });

  test('tied live games stay pending, and final ties only count in the regular season', () => {
    expect(liveOutcome(game(), 'REG')).toBe('TB');
    expect(liveOutcome(game({ homeScore: '24' }), 'REG')).toBe('ATL');
    const tied = game({ awayScore: '0', homeScore: '0' });
    expect(liveOutcome(tied, 'REG')).toBeNull();
    expect(liveOutcome({ ...tied, state: 'post', completed: true }, 'REG')).toBe('TIE');
    expect(liveOutcome({ ...tied, state: 'post', completed: true }, 'SB')).toBeNull();
    for (const changes of [{ state: 'pre' }, { state: 'post', completed: false },
      { scoresAvailable: false }, { awayScore: '' }, { awayScore: null }, { homeScore: -1 },
      { homeScore: 'bad' }, { statusName: 'STATUS_SUSPENDED' }]) {
      expect(liveOutcome(game(changes), 'REG')).toBeNull();
    }
    expect(liveOutcome(null, 'REG')).toBeNull();
  });

  test('replaces leads, counts finals once, and rebases without double-counting', () => {
    const d = seed(); const events = [game()];
    expect(livePoolStandings(d, events, NOW).rows.map((e) => [e.name, e.total, e.rank]))
      .toEqual([['Alex', 12, 1], ['Cam', 11, 2], ['Blair', 10, 3]]);
    expect(livePoolStandings(d, events, NOW)).toEqual(livePoolStandings(d, events, NOW));
    expect(livePoolStandings(d, [game({ homeScore: 24 })], NOW).rows[0].name).toBe('Blair');
    expect(livePoolStandings(d, [game({ homeScore: 21 })], NOW).contributing).toBe(0);
    const final = game({ state: 'post', completed: true });
    const updated = clone(d);
    updated.entrants[0].banked += 2; updated.entrants[2].banked += 2; updated.games[0].scored = true;
    expect(livePoolStandings(updated, [final], NOW).rows.map((r) => r.total))
      .toEqual(livePoolStandings(d, [final], NOW).rows.map((r) => r.total));
    expect(livePoolStandings(updated, [final], NOW).contributing).toBe(0);
    expect(livePoolStandings(d, [], NOW).missing).toBe(1);
    expect(livePoolStandings(d, [], NOW - 10_000_000).missing).toBe(0);
    const ties = livePoolStandings(d, [game({ state: 'post', completed: true, homeScore: 21 })], NOW);
    expect(ties.rows.map((e) => [e.name, e.total, e.rank])).toEqual([['Blair', 11.5, 1], ['Cam', 11.5, 1], ['Alex', 11, 3]]);
  });

  test('rounds before ranking and uses supplied postseason gains', () => {
    const d = seed(); d.entrants = d.entrants.slice(0, 2);
    d.entrants[0].banked = 0.1; d.entrants[1].banked = 0.3;
    d.games[0].kind = 'WC'; d.games[0].points.alex.TB = 0.2;
    const result = livePoolStandings(d, [game({ seasonType: 3 })], NOW);
    expect(result.rows.map((e) => [e.total, e.rank])).toEqual([[0.3, 1], [0.3, 1]]);
  });

  test('parses a captured full game, deduplicates current drives, and accepts corrections', () => {
    const data = summary();
    const first = parseLiveSummary(data, helpers);
    expect(first.plays).toHaveLength(6);
    expect(first.playerStats).toHaveLength(6);
    expect(first.quarters).toHaveLength(2);
    expect(first.event.week).toBe(1);
    data.drives.current = clone(data.drives.previous[0]);
    data.drives.current.plays[0].text = 'Corrected play description';
    data.drives.current.plays[0].isTurnover = true;
    const next = parseLiveSummary(data, helpers);
    expect(next.plays).toHaveLength(6);
    expect(next.plays.find((p) => p.id === data.drives.current.plays[0].id).text).toBe('Corrected play description');
    expect(next.drives).toHaveLength(2);
    data.boxscore.players[0].statistics[0].athletes[0].stats = [];
    expect(parseLiveSummary(data, helpers).playerStats).toHaveLength(5);
    expect(() => parseLiveSummary({}, helpers)).toThrow();
    data.header.id = 'bad'; expect(() => parseLiveSummary(data, helpers)).toThrow();
  });

  test('missing optional details remain empty; field direction follows possession', () => {
    const d = summary('pre'); delete d.drives; delete d.scoringPlays; delete d.boxscore; delete d.gameInfo;
    for (const c of d.header.competitions[0].competitors) delete c.linescores;
    const parsed = parseLiveSummary(d, helpers);
    expect(parsed.drives).toEqual([]); expect(parsed.teamStats).toEqual([]); expect(parsed.playerStats).toEqual([]);
    expect(liveFieldPosition(game(), normalizeEspnTeam)).toEqual({ ball: 80, first: 88,
      direction: 1, toGoal: 20, goalToGo: false, spot: 'ATL 20', target: 'ATL 12' });
    expect(liveFieldPosition(game({ possession: 'ATL' }), normalizeEspnTeam))
      .toMatchObject({ ball: 80, first: 72, direction: -1, toGoal: 80, target: 'ATL 28' });
    expect(liveFieldPosition(game({ distance: 30 }), normalizeEspnTeam).first).toBe(100);
    for (const g of [game({ state: 'post' }), game({ down: '' }), game({ possession: '' }),
      game({ down: '1st & 10 at XXX 20' }), game({ down: '1st & 10 at ATL 60' })]) expect(liveFieldPosition(g, normalizeEspnTeam)).toBeNull();
  });

  test('places midfield, goal-to-go, and missing-distance markers without inventing a first down', () => {
    expect(liveFieldPosition(game({ down: '1st & 10 at 50', distance: 10 }), normalizeEspnTeam))
      .toMatchObject({ ball: 50, first: 60, spot: 'Midfield', target: 'ATL 40' });
    expect(liveFieldPosition(game({ down: '1st & Goal at TB 3', possession: 'ATL', distance: 3 }), normalizeEspnTeam))
      .toMatchObject({ ball: 3, first: 0, direction: -1, toGoal: 3, goalToGo: true, target: 'Goal line' });
    expect(liveFieldPosition(game({ down: '2nd & Goal at ATL 1', distance: 0 }), normalizeEspnTeam))
      .toMatchObject({ ball: 99, first: 100, toGoal: 1, goalToGo: true });
    for (const distance of [0, undefined, NaN, Infinity, -2]) {
      expect(liveFieldPosition(game({ distance }), normalizeEspnTeam)).toMatchObject({ first: null, target: '' });
    }
    for (const down of [undefined, 'Kickoff', '1st & 10 at 20', '1st & 10 at TB 100', '1st & 10 at TB 3.5']) {
      expect(liveFieldPosition(game({ down }), normalizeEspnTeam)).toBeNull();
    }
  });

  test('chooses relevant live games and reduces requests as football ends', () => {
    expect(chooseLiveGame([game(), game({ id: '999', away: 'NE' })], ['NE']).id).toBe('999');
    expect(chooseLiveGame([game()]).id).toBe(ID);
    expect(chooseLiveGame([game({ state: 'pre' })]).id).toBe(ID);
    expect(chooseLiveGame([game({ state: 'post' })]).id).toBe(ID);
    expect(chooseLiveGame([])).toBeNull();
    expect(liveRefreshDelay([game()])).toBe(LIVE_INTERVAL);
    expect(liveRefreshDelay([game()], 0, FAST_LIVE_INTERVAL)).toBe(FAST_LIVE_INTERVAL);
    expect(liveRefreshDelay([game({ state: 'pre' })], 0, FAST_LIVE_INTERVAL)).toBe(WAIT_INTERVAL);
    expect(liveRefreshDelay([game({ state: 'pre' })])).toBe(WAIT_INTERVAL);
    expect(liveRefreshDelay([game({ state: 'post', completed: true })])).toBe(0);
    expect(liveRefreshDelay([], 1)).toBe(60_000);
    expect(liveRefreshDelay([], 5)).toBe(WAIT_INTERVAL);
    expect(liveScoreboardUrl(seed().windows[0])).toContain('dates=20250907-20250908&limit=1000');
  });
});

function markup(data) {
  document.body.innerHTML = `
    <select data-me-select><option value="">Everyone</option><option value="alex">Alex</option></select>
    <select data-tz-select><option>America/New_York</option><option>UTC</option></select>
    <button data-live-refresh>Refresh</button><p data-live-connection></p>
    <button data-live-fast-refresh aria-pressed="false">5-second updates <span data-live-fast-state aria-hidden="true">Off</span></button>
    <div data-live-center data-baseline-url="/data/live.json" data-entrant-base="/entrant/">
      <h2 data-live-slate-title></h2><nav data-live-game-rail></nav>
      <span data-live-game-status></span><a data-live-espn></a><div data-live-scoreboard></div>
      <p data-live-situation-text></p><span data-live-venue></span><button data-live-copy>Copy</button><p data-live-share-status></p>
      <div role="tablist">${['overview', 'plays', 'stats'].map((v) => `<button data-live-view="${v}" aria-controls="panel-${v}" aria-selected="${v === 'overview'}" tabindex="${v === 'overview' ? 0 : -1}">${v}</button>`).join('')}</div>
      ${['overview', 'plays', 'stats'].map((v) => `<section id="panel-${v}" ${v === 'overview' ? '' : 'hidden'}></section>`).join('')}
      <p data-live-detail-status></p><p data-live-field-label></p>
      <div data-live-field-head><span data-live-possession-chip></span><strong data-live-possession-name></strong>
        <div data-live-direction><span data-live-direction-arrow></span><span data-live-direction-text></span></div></div>
      <div data-live-field><svg><g data-live-away-end><text></text></g><g data-live-home-end><text></text></g>
        <g data-live-ball></g><g data-live-first-down></g><g data-live-scrimmage></g><g data-live-attack-arrow></g></svg></div>
      <div data-live-field-legend><span data-live-spot></span><span data-live-target><span data-live-target-text></span></span><span data-live-goal-distance></span></div>
      <div data-live-stakes></div><div data-live-quarters></div><ol data-live-scoring></ol>
      <div data-live-drives></div><p data-live-play-notice></p><div data-live-team-stats></div><div data-live-player-stats></div>
      <ol data-live-standings><li>Static standings</li></ol><p data-live-board-status></p>
      <span data-live-chip="TB"><a class="team-chip" href="/team/TB/" style="--team-bg:#d50a0a;--team-fg:#ffffff;--team-edge:#ff7900">TB</a></span>
      <script id="live-data" type="application/json">${JSON.stringify(data)}</script>
    </div>`;
}

describe('Live page controller', () => {
  let controller; let baseline; let details; let board; let fetcher;
  const $ = (s) => document.querySelector(s);
  const flush = () => setImmediate();
  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(NOW);
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true });
    window.history.replaceState(null, '', '/live/');
    window.localStorage.removeItem('pool-live-fast-refresh');
    baseline = seed(); details = summary(); board = scoreboard(details);
    fetcher = vi.fn(async (url) => ({ ok: true, status: 200, json: async () => clone(
      String(url).includes('summary?') ? details : String(url).includes('scoreboard?') ? board : baseline) }));
    window.fetch = fetcher;
    markup(baseline);
  });
  afterEach(() => { controller?.destroy(); controller = null; vi.useRealTimers(); vi.restoreAllMocks(); });
  async function start() { controller = initLivePage(document, window, helpers); await controller.ready; await flush(); }
  const requestsFor = (name) => fetcher.mock.calls.filter(([url]) => String(url).includes(name)).length;

  test('switches both feeds to five seconds and back without keeping old timers', async () => {
    await start();
    const toggle = $('[data-live-fast-refresh]');
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    toggle.click();
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    expect(toggle.textContent).toContain('On');
    expect(window.localStorage.getItem('pool-live-fast-refresh')).toBe('true');
    await vi.advanceTimersByTimeAsync(FAST_LIVE_INTERVAL - 1);
    expect(requestsFor('scoreboard?')).toBe(1); expect(requestsFor('summary?')).toBe(1);
    await vi.advanceTimersByTimeAsync(1 + FAST_LIVE_INTERVAL * 2);
    expect(requestsFor('scoreboard?')).toBe(4); expect(requestsFor('summary?')).toBe(4);
    toggle.click();
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    expect(toggle.textContent).toContain('Off');
    expect(window.localStorage.getItem('pool-live-fast-refresh')).toBe('false');
    await vi.advanceTimersByTimeAsync(LIVE_INTERVAL - 1);
    expect(requestsFor('scoreboard?')).toBe(4); expect(requestsFor('summary?')).toBe(4);
    await vi.advanceTimersByTimeAsync(1);
    expect(requestsFor('scoreboard?')).toBe(5); expect(requestsFor('summary?')).toBe(5);
    expect(requestsFor('live.json')).toBe(1);
  });

  test('restores the five-second preference on a new page', async () => {
    window.localStorage.setItem('pool-live-fast-refresh', 'true');
    await start();
    expect($('[data-live-fast-refresh]').getAttribute('aria-pressed')).toBe('true');
    await vi.advanceTimersByTimeAsync(FAST_LIVE_INTERVAL);
    expect(requestsFor('scoreboard?')).toBe(2); expect(requestsFor('summary?')).toBe(2);
  });

  test('can change refresh speed when browser storage is blocked', async () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new Error('Storage blocked'); });
    await start();
    $('[data-live-fast-refresh]').click();
    expect($('[data-live-fast-refresh]').getAttribute('aria-pressed')).toBe('true');
    await vi.advanceTimersByTimeAsync(FAST_LIVE_INTERVAL);
    expect(requestsFor('scoreboard?')).toBe(2); expect(requestsFor('summary?')).toBe(2);
  });

  test('changing speed during a request uses the new interval without overlapping requests', async () => {
    const original = fetcher.getMockImplementation();
    let release;
    fetcher.mockImplementation((url, options) => String(url).includes('summary?')
      ? new Promise((resolve) => { release = () => resolve(original(url, options)); })
      : original(url, options));
    controller = initLivePage(document, window, helpers); await flush();
    $('[data-live-fast-refresh]').click();
    await vi.advanceTimersByTimeAsync(FAST_LIVE_INTERVAL);
    expect(requestsFor('scoreboard?')).toBe(1); expect(requestsFor('summary?')).toBe(1);
    fetcher.mockImplementation(original); release(); await controller.ready;
    await vi.advanceTimersByTimeAsync(FAST_LIVE_INTERVAL);
    expect(requestsFor('scoreboard?')).toBe(2); expect(requestsFor('summary?')).toBe(2);
  });

  test('loads real adapter shapes, renders game views and standings, and supports sharing', async () => {
    await start();
    expect($('[data-live-scoreboard]').textContent).toContain('TB21');
    expect($('[data-live-scoreboard]').textContent).toContain('ATL17');
    expect($('[data-live-field]').hidden).toBe(false);
    expect($('[data-live-field]').getAttribute('aria-label')).toContain('TB ball');
    expect($('[data-live-stakes]').textContent).toContain('Alex, Cam · 2.00');
    expect($('[data-live-standings]').textContent).toContain('1. Alex+2.0012.00');
    expect(document.querySelectorAll('[data-play]')).toHaveLength(6);
    expect(document.querySelectorAll('[data-live-player-stats] table')).toHaveLength(6);
    expect($('[data-live-espn]').href).toContain(ID);
    $('[data-live-view="plays"]').click();
    expect($('#panel-overview').hidden).toBe(true); expect($('#panel-plays').hidden).toBe(false);
    $('[data-live-view="plays"]').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(document.activeElement.dataset.liveView).toBe('stats');
    document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    expect(document.activeElement.dataset.liveView).toBe('overview');
    document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    Object.defineProperty(window.navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(async () => {}) } });
    $('[data-live-copy]').click(); await flush();
    expect(window.navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining(`game=${ID}`));
    expect($('[data-live-share-status]').textContent).toContain('copied');
    window.navigator.clipboard.writeText.mockRejectedValueOnce(new Error('denied'));
    $('[data-live-copy]').click(); await flush(); expect($('[data-live-share-status]').textContent).toContain('browser');
    $('[data-me-select]').value = 'alex'; $('[data-me-select]').dispatchEvent(new Event('change'));
    expect($('[data-entrant="alex"]').classList.contains('is-me')).toBe(true);
    $('[data-tz-select]').value = 'UTC'; $('[data-tz-select]').dispatchEvent(new Event('change'));
    expect($('[data-live-board-status]').textContent).toContain('UTC');
  });

  test('keeps end zones fixed while possession, scrimmage, and first-down markers follow the drive', async () => {
    const competition = board.events[0].competitions[0];
    const home = competition.competitors.find((c) => c.homeAway === 'home');
    competition.competitors.find((c) => c.homeAway === 'away').team.name = 'Buccaneers';
    home.team.name = 'Falcons';
    await start();
    const awayEnd = $('[data-live-away-end]'); const homeEnd = $('[data-live-home-end]');
    expect(awayEnd.textContent).toBe('BUCCANEERS'); expect(homeEnd.textContent).toBe('FALCONS');
    expect(awayEnd.style.getPropertyValue('--team-bg')).toBe('#d50a0a');
    expect($('[data-live-possession-name]').textContent).toBe('Buccaneers ball');
    expect($('[data-live-direction-text]').textContent).toBe('Driving right');
    expect($('[data-live-scrimmage]').style.transform).toBe('translateX(900px)');
    expect($('[data-live-ball]').style.transform).toBe('translate(900px, 266.67px)');
    expect($('[data-live-first-down]').style.transform).toBe('translateX(980px)');
    expect($('[data-live-field]').getAttribute('aria-label')).toContain('First down: ATL 12');
    competition.situation.possession = home.id;
    await vi.advanceTimersByTimeAsync(LIVE_INTERVAL);
    expect(awayEnd.textContent).toBe('BUCCANEERS'); expect(homeEnd.textContent).toBe('FALCONS');
    expect($('[data-live-possession-name]').textContent).toBe('Falcons ball');
    expect($('[data-live-possession-chip]').textContent).toBe('ATL');
    expect($('[data-live-direction-arrow]').textContent).toBe('←');
    expect($('[data-live-direction-text]').textContent).toBe('Driving left');
    expect($('[data-live-scrimmage]').style.transform).toBe('translateX(900px)');
    expect($('[data-live-first-down]').style.transform).toBe('translateX(820px)');
    expect($('[data-live-goal-distance]').textContent).toBe('80 yards to goal');
    competition.situation.downDistanceText = '1st & Goal at TB 1'; competition.situation.distance = 1;
    await vi.advanceTimersByTimeAsync(LIVE_INTERVAL);
    expect($('[data-live-scrimmage]').style.transform).toBe('translateX(110px)');
    expect($('[data-live-first-down]').style.transform).toBe('translateX(100px)');
    expect($('[data-live-target-text]').textContent).toBe('Goal line');
    expect($('[data-live-goal-distance]').textContent).toBe('1 yard to goal');
    competition.situation.downDistanceText = '1st & 10 at TB 1'; delete competition.situation.distance;
    await vi.advanceTimersByTimeAsync(LIVE_INTERVAL);
    expect($('[data-live-first-down]').style.display).toBe('none');
    expect($('[data-live-target]').hidden).toBe(true);
    delete competition.situation.possession;
    await vi.advanceTimersByTimeAsync(LIVE_INTERVAL);
    expect($('[data-live-field]').hidden).toBe(true);
    expect($('[data-live-field-head]').hidden).toBe(true);
    expect($('[data-live-field-legend]').hidden).toBe(true);
  });

  test('polls without duplicate requests, preserves expanded drives, and replaces corrected plays', async () => {
    await start(); const drive = $('[data-drive]'); drive.open = false;
    const tile = $('[data-key]'); tile.focus();
    $('[data-live-player-stats] .live-table-wrap').scrollLeft = 40;
    const previousId = drive.dataset.drive;
    details.drives.previous[0].plays[0].text = '<img src=x onerror=alert(1)> Correction';
    const newPlay = { ...details.drives.previous[0].plays[0], id: 'new-play', sequenceNumber: '999999', text: 'New touchdown', scoringPlay: true, period: { number: 5 } };
    details.drives.previous[0].plays.push(newPlay);
    board.events[0].competitions[0].competitors.find((c) => c.homeAway === 'home').score = '24';
    await vi.advanceTimersByTimeAsync(LIVE_INTERVAL); await flush();
    expect(requestsFor('summary?')).toBe(2); expect(requestsFor('scoreboard?')).toBe(2);
    expect($(`[data-drive="${previousId}"]`).open).toBe(false);
    expect($('[data-live-play-notice]').textContent).toContain('1 new play');
    expect($('[data-play="new-play"]').textContent).toContain('OT');
    expect($('[data-live-drives] img')).toBeNull();
    expect($('[data-live-standings]').firstChild.textContent).toContain('Blair');
    expect($('[data-live-scoreboard]').textContent).toContain('ATL24');
    expect(document.activeElement).toBe(tile);
    expect($('[data-live-player-stats] .live-table-wrap').scrollLeft).toBe(40);
    const owner = $('[data-entrant="cam"] a'); owner.focus();
    board.events[0].competitions[0].competitors.find((c) => c.homeAway === 'away').score = '28';
    await vi.advanceTimersByTimeAsync(LIVE_INTERVAL); await flush();
    expect($('[data-live-play-notice]').textContent).toBe('');
    expect(document.activeElement).toBe(owner);
  });

  test('reloads the official baseline atomically and never carries another pool into it', async () => {
    await start();
    baseline = clone(baseline); baseline.generated = new Date(NOW + 1000).toISOString();
    baseline.entrants[0].banked = 12; baseline.entrants[2].banked = 11; baseline.games[0].scored = true;
    await vi.advanceTimersByTimeAsync(BASELINE_INTERVAL); await flush();
    expect($('[data-entrant="alex"]').lastChild.textContent).toBe('12.00');
    expect($('[data-entrant="alex"]').children[1].textContent).toBe('—');
    baseline.pool = 'friends'; baseline.entrants[0].name = 'Other pool member';
    await controller.refresh();
    expect($('[data-live-standings]').textContent).not.toContain('Other pool member');
    expect($('[data-live-board-status]').textContent).toContain('Official refresh unavailable');
  });

  test('survives feed failures and recovers via automatic backoff and manual refresh', async () => {
    await start();
    fetcher.mockImplementation(async () => { throw new Error('network'); });
    await vi.advanceTimersByTimeAsync(LIVE_INTERVAL); await flush();
    expect($('[data-live-connection]').textContent).toContain('unavailable');
    expect($('[data-live-detail-status]').textContent).toContain('Last update');
    expect($('[data-live-scoreboard]').textContent).toContain('21');
    const count = fetcher.mock.calls.length;
    $('[data-live-fast-refresh]').click();
    await vi.advanceTimersByTimeAsync(59_000); expect(fetcher.mock.calls.length).toBe(count);
    fetcher.mockImplementation(async (url) => ({ ok: true, status: 200, json: async () => String(url).includes('summary?') ? clone(details) : String(url).includes('scoreboard?') ? clone(board) : clone(baseline) }));
    await vi.advanceTimersByTimeAsync(1000); await flush();
    expect($('[data-live-connection]').textContent).toContain('Scores updated');
    const recovered = fetcher.mock.calls.length;
    await vi.advanceTimersByTimeAsync(FAST_LIVE_INTERVAL);
    expect(fetcher.mock.calls.length).toBe(recovered + 2);
    $('[data-live-refresh]').click(); await flush();
    expect($('[data-live-detail-status]').textContent).toContain('updated');
  });

  test('pauses when hidden or offline and resumes on return', async () => {
    await start();
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
    const count = fetcher.mock.calls.length;
    $('[data-live-fast-refresh]').click();
    await vi.advanceTimersByTimeAsync(600_000); expect(fetcher.mock.calls.length).toBe(count);
    expect($('[data-live-connection]').textContent).toContain('paused');
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange')); await flush();
    expect(fetcher.mock.calls.length).toBeGreaterThan(count);
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
    window.dispatchEvent(new Event('offline'));
    expect($('[data-live-connection]').textContent).toContain('Offline');
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true });
    window.dispatchEvent(new Event('online')); await flush();
    window.dispatchEvent(new Event('pagehide')); window.dispatchEvent(new Event('pageshow')); await flush();
  });

  test('deep links resolve without ESPN IDs and history restores selection', async () => {
    baseline.games[0].espnId = ''; markup(baseline);
    window.history.replaceState(null, '', '/live/?matchup=2025_01_TB_ATL');
    await start();
    expect(window.location.search).toBe(`?game=${ID}`);
    $('[data-key]').click(); await flush();
    expect($('[data-key]').getAttribute('aria-pressed')).toBe('true');
    window.history.replaceState(null, '', '/live/'); window.dispatchEvent(new PopStateEvent('popstate')); await flush();
    expect($('[data-live-scoreboard]').textContent).toContain('TB21');
  });

  test('final games stop ESPN polling while the official baseline can still refresh', async () => {
    details = summary('post'); board = scoreboard(details);
    await start(); const count = fetcher.mock.calls.length;
    $('[data-live-fast-refresh]').click();
    await vi.advanceTimersByTimeAsync(WAIT_INTERVAL); expect(fetcher.mock.calls.length).toBe(count);
    await vi.advanceTimersByTimeAsync(BASELINE_INTERVAL - WAIT_INTERVAL); await flush();
    expect(requestsFor('scoreboard?')).toBe(1); expect(requestsFor('summary?')).toBe(1);
    expect(requestsFor('live.json')).toBe(2);
  });

  test('pregame and malformed details show useful empty states and never fake scores', async () => {
    details = summary('pre'); delete details.drives; delete details.boxscore; delete details.scoringPlays;
    for (const c of details.header.competitions[0].competitors) { delete c.linescores; delete c.score; }
    board = scoreboard(details); await start();
    expect($('[data-live-scoreboard]').textContent).toContain('TB—');
    expect($('[data-live-drives]').textContent).toContain('not been reported');
    expect($('[data-live-player-stats]').textContent).toContain('not been reported');
    expect($('[data-live-field]').hidden).toBe(true);
    details.header.id = '777'; await controller.refresh();
    expect($('[data-live-detail-status]').textContent).toContain('unavailable');
    expect($('[data-live-standings]').textContent).toContain('10.00');
  });

  test('an empty schedule still provides the official board and unrelated pages do nothing', async () => {
    baseline.games = []; baseline.windows = []; markup(baseline);
    await start(); expect($('[data-live-game-status]').textContent).toContain('No matchup');
    expect(requestsFor('scoreboard?')).toBe(0);
    controller.destroy(); controller = null; document.body.innerHTML = '';
    expect(initLivePage(document, window, helpers)).toBeNull();
  });

  test('switching games aborts the old request and ignores its late response', async () => {
    const other = summary('pre', '999');
    const comp = other.header.competitions[0];
    comp.competitors.find((c) => c.homeAway === 'away').team.abbreviation = 'NE';
    comp.competitors.find((c) => c.homeAway === 'home').team.abbreviation = 'SEA';
    delete other.drives; delete other.boxscore; delete other.scoringPlays;
    baseline.games.push({ ...clone(baseline.games[0]), id: '2025_01_NE_SEA', espnId: '999',
      away: 'NE', home: 'SEA', points: Object.fromEntries(baseline.entrants.map((e) => [e.slug, { NE: 0, SEA: 0, TIE: 0 }])) });
    board.events.push(scoreboard(other).events[0]); markup(baseline);
    let release; let oldSignal;
    fetcher.mockImplementation(async (url, options) => {
      if (String(url).endsWith(`summary?event=${ID}`)) {
        oldSignal = options.signal;
        return new Promise((resolve) => { release = () => resolve({ ok: true, status: 200, json: async () => clone(details) }); });
      }
      return { ok: true, status: 200, json: async () => clone(String(url).includes('summary?') ? other : String(url).includes('scoreboard?') ? board : baseline) };
    });
    controller = initLivePage(document, window, helpers); await flush();
    expect(oldSignal.aborted).toBe(false);
    $('[data-event="999"]').click(); await flush();
    expect(oldSignal.aborted).toBe(true);
    expect($('[data-live-scoreboard]').textContent).toContain('NE');
    expect($('[data-live-drives]').textContent).toContain('not been reported');
    release(); await controller.ready; await flush();
    expect($('[data-live-scoreboard]').textContent).not.toContain('ATL');
    expect($('[data-live-standings]').textContent).toContain('12.00');
    expect(window.location.search).toBe('?game=999');
  });

  test('a timed-out summary backs off even when scoreboard polling stays healthy', async () => {
    let hanging = true;
    fetcher.mockImplementation(async (url, options) => {
      if (String(url).includes('summary?') && hanging) return new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
      });
      return { ok: true, status: 200, json: async () => clone(String(url).includes('summary?') ? details : String(url).includes('scoreboard?') ? board : baseline) };
    });
    controller = initLivePage(document, window, helpers); await flush();
    await vi.advanceTimersByTimeAsync(10_000); await controller.ready;
    expect($('[data-live-detail-status]').textContent).toContain('unavailable');
    expect(requestsFor('summary?')).toBe(1);
    await vi.advanceTimersByTimeAsync(59_000); expect(requestsFor('summary?')).toBe(1);
    hanging = false; await vi.advanceTimersByTimeAsync(1000); await flush();
    expect(requestsFor('summary?')).toBe(2);
    expect($('[data-live-detail-status]').textContent).toContain('updated');
  });

  test('an unmatched preseason game displays details without inventing pool gains', async () => {
    details = summary('in', '999'); details.header.season.type = 1;
    window.history.replaceState(null, '', '/live/?game=999');
    await start();
    expect($('[data-live-stakes]').textContent).toContain('Preseason');
    expect($('[data-live-standings]').textContent).toContain('12.00');
    expect($('[data-live-scoreboard]').textContent).toContain('TB');
    window.history.replaceState(null, '', '/live/?game=888');
    window.dispatchEvent(new PopStateEvent('popstate')); await flush();
    expect($('[data-live-scoreboard]').textContent).toBe('');
    expect($('[data-live-detail-status]').textContent).toContain('unavailable');
  });

  test('retains complete scores across a regressed feed and accepts final corrections', async () => {
    details = summary('post'); board = scoreboard(details); await start();
    board = scoreboard(summary('in')); board.events[0].competitions[0].competitors[0].score = '99';
    await controller.refresh();
    expect($('[data-live-game-status]').textContent).toBe('Final');
    expect($('[data-live-scoreboard]').textContent).not.toContain('99');
    board.events[0].status.type.completed = true; board.events[0].status.type.state = 'post';
    await controller.refresh();
    expect($('[data-live-scoreboard]').textContent).toContain('99');
    expect($('[data-live-standings]').firstChild.textContent).toContain('Blair');
    baseline.generated = '2025-09-06T00:00:00Z'; baseline.entrants[0].banked = 999;
    await controller.refresh(); expect($('[data-live-standings]').textContent).not.toContain('999.00');
  });

  test('loads older unbanked finals even when another week is selected', async () => {
    const older = clone(baseline.games[0]); older.week = 1;
    baseline.games.push({ ...clone(older), id: '2025_02_TB_ATL', espnId: '999', week: 2,
      date: '2025-09-14', kickoff: '2025-09-14T17:00:00Z' });
    baseline.windows.push({ ...baseline.windows[0], key: 'REG-2', week: 2, label: 'Week 2',
      start: '20250914', end: '20250915', closes: '2025-09-16T04:00:00Z' });
    vi.setSystemTime('2025-09-14T18:00:00Z'); markup(baseline);
    const oldBoard = scoreboard(summary('post'));
    const current = summary('pre', '999'); current.header.week = 2;
    current.header.competitions[0].date = '2025-09-14T19:00:00Z';
    fetcher.mockImplementation(async (url) => ({ ok: true, status: 200,
      json: async () => clone(String(url).includes('summary?') ? current : String(url).includes('20250907') ? oldBoard : String(url).includes('scoreboard?') ? scoreboard(current) : baseline) }));
    await start();
    expect($('[data-live-slate-title]').textContent).toBe('Week 2');
    expect($('[data-live-standings]').textContent).toContain('12.00');
    expect($('[data-live-board-status]').textContent).toContain('1 game contributing');
    expect(requestsFor('scoreboard?')).toBe(2);
    oldBoard.events[0].status.type.state = 'in';
    oldBoard.events[0].status.type.completed = false;
    controller.destroy(); controller = null;
    window.history.replaceState(null, '', '/live/'); markup(baseline);
    await start();
    expect($('[data-live-game-rail]').children).toHaveLength(2);
    expect($('[data-live-game-rail]').firstChild.dataset.event).toBe(ID);
  });

  test('invalid scoreboards preserve static content and are retried', async () => {
    board = { bad: 'response' }; await start();
    expect($('[data-live-connection]').textContent).toContain('unavailable');
    expect($('[data-live-board-status]').textContent).toContain('awaiting scores');
    board = { events: [{}] }; await controller.refresh();
    expect($('[data-live-connection]').textContent).toContain('unavailable');
    board = scoreboard(); await controller.refresh();
    expect($('[data-live-board-status]').textContent).not.toContain('awaiting scores');
  });
});
