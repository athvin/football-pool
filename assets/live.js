/** Browser-only Game Center. The build supplies rules and a scoring baseline;
 * ESPN supplies observations. Never add a delta to an already-updated total. */
export const LIVE_INTERVAL = 20_000;
export const FAST_LIVE_INTERVAL = 5_000;
export const WAIT_INTERVAL = 180_000;
export const BASELINE_INTERVAL = 300_000;
export const ESPN_BASE = 'https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/';
const PHASE = { REG: 2, WC: 3, DIV: 3, CON: 3, SB: 3 };
const PLAYOFF_WEEK = { WC: 1, DIV: 2, CON: 3, SB: 5 };
const FAST_REFRESH_KEY = 'pool-live-fast-refresh';
const eventId = (id) => /^\d+$/.test(String(id));
const cents = (value) => Math.round(Number(value) * 100);
const points = (value) => Number(value).toFixed(2);

export function validateLiveBaseline(data) {
  const valid = data?.version === 1 && Number.isInteger(data.season)
    && typeof data.pool === 'string' && Number.isFinite(Date.parse(data.generated))
    && Array.isArray(data.entrants) && data.entrants.length > 0
    && data.entrants.every((e) => typeof e.slug === 'string' && /^[\w-]+$/.test(e.slug)
      && typeof e.name === 'string' && Array.isArray(e.teams)
      && Number.isFinite(e.banked) && e.banked >= 0)
    && Array.isArray(data.games) && data.games.every((g) => typeof g.id === 'string'
      && PHASE[g.kind] && Number.isInteger(g.week) && typeof g.scored === 'boolean'
      && typeof g.away === 'string' && typeof g.home === 'string' && g.away !== g.home
      && Number.isFinite(Date.parse(g.kickoff)) && /^\d{4}-\d{2}-\d{2}$/.test(g.date)
      && (!g.espnId || eventId(g.espnId)) && g.points && typeof g.points === 'object'
      && (g.scored || data.entrants.every((e) => {
        const gains = g.points[e.slug];
        return gains && [g.away, g.home, ...(g.kind === 'REG' ? ['TIE'] : [])]
          .every((outcome) => Number.isFinite(gains[outcome]) && gains[outcome] >= 0);
      })))
    && Array.isArray(data.windows) && data.windows.every((w) => typeof w.key === 'string'
      && PHASE[w.kind] && Number.isInteger(w.week) && typeof w.label === 'string'
      && /^\d{8}$/.test(w.start) && /^\d{8}$/.test(w.end)
      && Number.isFinite(Date.parse(w.closes)));
  if (!valid || new Set(data.entrants.map((e) => e.slug)).size !== data.entrants.length
    || new Set(data.games.map((g) => g.id)).size !== data.games.length) {
    throw new Error('Invalid live scoring baseline');
  }
  return data;
}

/** IDs survive rescheduling. Without one, require an unambiguous season/phase
 * and matchup, with the same ESPN week or Eastern calendar date. */
export function matchLiveGame(game, events, season) {
  const candidates = events.filter((e) => e.seasonYear === season
    && e.seasonType === PHASE[game.kind] && e.away === game.away && e.home === game.home);
  const byId = candidates.find((e) => game.espnId && e.id === game.espnId);
  if (byId) return byId;
  const matches = candidates.filter((e) => {
    const day = Number.isFinite(Date.parse(e.date))
      ? new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York',
        year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(e.date)) : '';
    return day === game.date || e.week === (PLAYOFF_WEEK[game.kind] || game.week);
  });
  return matches.length === 1 ? matches[0] : null;
}

export function liveOutcome(event, kind) {
  if (!event || event.scoresAvailable === false
    || !['in', 'post'].includes(event.state)
    || /CANCEL|POSTPON|SUSPEND/.test(event.statusName || '')
    || (event.state === 'post' && !event.completed)) return null;
  const scores = [event.awayScore, event.homeScore];
  if (scores.some((s) => s == null || String(s).trim() === ''
    || !Number.isInteger(Number(s)) || Number(s) < 0)) return null;
  const [away, home] = scores.map(Number);
  if (away === home) return event.completed && kind === 'REG' ? 'TIE' : null;
  return away > home ? event.away : event.home;
}

export function livePoolStandings(baseline, events, nowMs) {
  const totals = new Map(baseline.entrants.map((e) => [e.slug, cents(e.banked)]));
  let missing = 0;
  let contributing = 0;
  for (const game of baseline.games) {
    if (game.scored) continue;
    const event = matchLiveGame(game, events, baseline.season);
    if (!event && Date.parse(game.kickoff) <= nowMs) missing++;
    const outcome = liveOutcome(event, game.kind);
    if (!outcome) continue;
    contributing++;
    for (const entrant of baseline.entrants) {
      totals.set(entrant.slug, totals.get(entrant.slug) + cents(game.points[entrant.slug][outcome]));
    }
  }
  const rows = baseline.entrants.map((e) => ({ ...e, total: totals.get(e.slug) / 100,
    delta: (totals.get(e.slug) - cents(e.banked)) / 100,
    bankedRank: 1 + baseline.entrants.filter((other) => cents(other.banked) > cents(e.banked)).length,
  })).sort((a, b) => cents(b.total) - cents(a.total) || a.name.localeCompare(b.name));
  for (const row of rows) row.rank = 1 + rows.filter((other) => cents(other.total) > cents(row.total)).length;
  return { rows, missing, contributing };
}

export function liveScoreboardUrl(window) {
  return `${ESPN_BASE}scoreboard?dates=${window.start}-${window.end}&limit=1000`;
}

export function liveRefreshDelay(events, failures = 0, liveInterval = LIVE_INTERVAL) {
  if (failures) return Math.min(60_000 * 2 ** (failures - 1), WAIT_INTERVAL);
  if (events.some((e) => e.state === 'in')) return liveInterval;
  if (!events.length || events.some((e) => e.state === 'pre' || !e.completed)) return WAIT_INTERVAL;
  return 0;
}

export function chooseLiveGame(events, picks = []) {
  const live = events.filter((e) => e.state === 'in');
  return live.find((e) => picks.includes(e.away) || picks.includes(e.home)) || live[0]
    || events.filter((e) => e.state === 'pre').sort((a, b) => a.date.localeCompare(b.date))[0]
    || [...events].sort((a, b) => b.date.localeCompare(a.date))[0] || null;
}

export function liveFieldPosition(event, normalizeTeam) {
  if (event?.state !== 'in' || ![event.away, event.home].includes(event.possession)) return null;
  const match = event.down?.match(/\bat (?:([A-Z]+) )?(\d{1,2})(?:\s|$)/);
  if (!match) return null;
  const side = normalizeTeam(match[1] || '');
  const yards = Number(match[2]);
  if ((side && ![event.away, event.home].includes(side)) || yards > 50 || (!side && yards !== 50)) return null;
  // Keep away/home end zones fixed. Coordinates describe this field view,
  // rather than a stadium compass direction, which the feed does not supply.
  const ball = side === event.away ? yards : 100 - yards;
  const direction = event.possession === event.away ? 1 : -1;
  const toGoal = direction === 1 ? 100 - ball : ball;
  const distance = Number(event.distance);
  const validDistance = Number.isFinite(distance) && distance > 0;
  const goalToGo = /&\s*Goal\b/i.test(event.down) || (validDistance && distance >= toGoal);
  const first = goalToGo ? (direction === 1 ? 100 : 0)
    : validDistance ? ball + direction * distance : null;
  const spot = (position) => position === 50 ? 'Midfield'
    : `${position < 50 ? event.away : event.home} ${position < 50 ? position : 100 - position}`;
  return { ball, first, direction, toGoal, goalToGo, spot: spot(ball),
    target: first === null ? '' : goalToGo ? 'Goal line' : spot(first) };
}

/** Keep the full latest snapshot, including corrected plays. Current drives
 * can also appear in previous; each play ID occurs only once in our model. */
export function parseLiveSummary(payload, helpers) {
  const header = payload?.header;
  const competition = header?.competitions?.[0];
  if (!header || !competition) throw new Error('Game details unavailable');
  const event = helpers.parseEspnScoreboard({ events: [{ ...header,
    week: { number: typeof header.week === 'number' ? header.week : header.week?.number },
    status: competition.status }] })[0];
  if (!event || !eventId(event.id)) throw new Error('Game details unavailable');
  event.venue = payload.gameInfo?.venue?.fullName || event.venue;
  const driveMap = new Map();
  const playMap = new Map();
  for (const [index, drive] of [...(payload.drives?.previous || []), payload.drives?.current].entries()) {
    if (!drive) continue;
    const id = String(drive.id || `drive-${index}`);
    driveMap.set(id, { id, team: helpers.normalizeEspnTeam(drive.team?.abbreviation || ''),
      result: drive.displayResult || drive.result || 'Drive in progress',
      yards: drive.yards, duration: drive.timeElapsed?.displayValue || '', plays: [] });
    for (const play of drive.plays || []) {
      if (!play.id || !play.text) continue;
      playMap.set(String(play.id), { id: String(play.id), drive: id, text: String(play.text),
        sequence: Number(play.sequenceNumber) || playMap.size,
        period: Number(play.period?.number || 0), clock: play.clock?.displayValue || '',
        scoring: Boolean(play.scoringPlay), turnover: Boolean(play.isTurnover),
        awayScore: play.awayScore, homeScore: play.homeScore });
    }
  }
  const plays = [...playMap.values()].sort((a, b) => b.sequence - a.sequence);
  for (const play of plays) driveMap.get(play.drive).plays.push(play);
  const drives = [...driveMap.values()].filter((d) => d.plays.length)
    .sort((a, b) => b.plays[0].sequence - a.plays[0].sequence);
  const quarters = competition.competitors.map((c) => ({
    team: helpers.normalizeEspnTeam(c.team.abbreviation),
    scores: (c.linescores || []).map((s) => String(s.displayValue ?? s.value ?? '—')),
  }));
  const teamStats = (payload.boxscore?.teams || []).map((t) => ({
    team: helpers.normalizeEspnTeam(t.team?.abbreviation || ''),
    stats: Object.fromEntries((t.statistics || []).map((s) => [s.name, s.displayValue])),
  }));
  const playerStats = (payload.boxscore?.players || []).flatMap((t) => (t.statistics || [])
    .filter((s) => ['passing', 'rushing', 'receiving'].includes(s.name))
    .map((s) => ({ team: helpers.normalizeEspnTeam(t.team?.abbreviation || ''), name: s.name,
      labels: s.labels || [], athletes: (s.athletes || [])
        .filter((a) => a.stats?.length === s.labels?.length)
        .map((a) => ({ name: a.athlete?.displayName || 'Player', stats: a.stats })) }))
    .filter((s) => s.labels.length && s.athletes.length));
  const scoring = (payload.scoringPlays || []).filter((p) => p.text).map((p) => ({
    text: p.text, clock: p.clock?.displayValue || '', period: p.period?.number || 0,
    awayScore: p.awayScore, homeScore: p.homeScore,
  }));
  return { event, drives, plays, quarters, teamStats, playerStats, scoring };
}

/** Each page owns one scoreboard loop and one selected-game request. The
 * injected browser and adapter also let tests exercise the real controller. */
export function initLivePage(doc, win, helpers) {
  const root = doc.querySelector('[data-live-center]');
  if (!root || typeof win.fetch !== 'function') return null;
  let baseline = validateLiveBaseline(JSON.parse(doc.querySelector('#live-data').textContent));
  const events = new Map();
  const fetchedWindows = new Set();
  const summaries = new Map();
  const requests = new Set();
  const listeners = [];
  const $ = (selector) => root.querySelector(selector);
  const now = () => (win.Date || Date).now();
  const active = () => !stopped && !doc.hidden && win.navigator.onLine !== false;
  const node = (tag, className = '', text = '') => {
    const element = doc.createElement(tag); element.className = className; element.textContent = text;
    return element;
  };
  const place = (parent, child, index) => {
    if (parent.children[index] === child) return;
    const focused = doc.activeElement;
    const restoreFocus = child.contains(focused);
    parent.insertBefore(child, parent.children[index] || null);
    if (restoreFocus) focused.focus({ preventScroll: true });
  };
  const listen = (target, name, callback) => {
    target.addEventListener(name, callback); listeners.push(() => target.removeEventListener(name, callback));
  };
  const zone = () => doc.querySelector('[data-tz-select]')?.value || 'America/New_York';
  const stamp = (time) => helpers.formatTimestamp(new Date(time).toISOString(), zone());
  const chipTemplates = new Map(Array.from(root.querySelectorAll('[data-live-chip]'),
    (el) => [el.dataset.liveChip, el.firstElementChild]));
  const chip = (team) => chipTemplates.get(team)?.cloneNode(true) || node('span', 'team-chip', team);
  const phaseClock = (p) => `${p.period > 4 ? 'OT' : `Q${p.period}`} ${p.clock}`.trim();
  let selected = '';
  let requestedMatchup = '';
  let pinned = false;
  let stopped = false;
  let running = false;
  let refreshPending = false;
  let timer;
  let detailTimer;
  let detailController;
  let detailGeneration = 0;
  let detailFailures = 0;
  let detailNextAt = 0;
  let failures = 0;
  let lastScoreUpdate = 0;
  let lastBaselineAttempt = -Infinity;
  let baselineUnavailable = false;
  let detailState = '';
  let renderedSummary = null;
  let liveInterval = LIVE_INTERVAL;
  try {
    if (win.localStorage.getItem(FAST_REFRESH_KEY) === 'true') liveInterval = FAST_LIVE_INTERVAL;
  } catch { /* The toggle still works when browser storage is unavailable. */ }

  const currentWindow = () => baseline.windows.find((w) => Date.parse(w.closes) > now())
    || baseline.windows.at(-1);
  const windowGames = (w) => baseline.games.filter((g) => g.week === w.week && g.kind === w.kind);
  const observed = (game) => matchLiveGame(game, [...events.values()], baseline.season);
  const staticEvent = (g) => ({ id: g.espnId, matchup: g.id, away: g.away, home: g.home,
    awayScore: g.awayScore, homeScore: g.homeScore, date: g.kickoff,
    state: g.scored ? 'post' : 'pre', completed: g.scored, status: g.scored ? 'Final' : '',
    scoresAvailable: g.scored, down: '', possession: '', venue: '', clock: '', distance: 0 });
  const slate = () => {
    const w = currentWindow();
    const order = { in: 0, pre: 1, post: 2 };
    const current = w ? windowGames(w) : [];
    // A long overtime or rescheduled game can outlive its schedule window.
    // Keep it selectable while the browser moves on to the next slate.
    const outsideLive = baseline.games.filter((g) => !current.includes(g) && observed(g)?.state === 'in');
    return [...current, ...outsideLive].map((g) => observed(g) || staticEvent(g))
      .sort((a, b) => order[a.state] - order[b.state]
        || (a.state === 'post' ? b.date.localeCompare(a.date) : a.date.localeCompare(b.date)));
  };
  const selectedKnown = () => baseline.games.find((g) => g.id === requestedMatchup
    || (selected && (g.espnId === selected || observed(g)?.id === selected)));
  const selectedEvent = () => events.get(selected) || summaries.get(selected)?.data.event
    || (selectedKnown() ? staticEvent(selectedKnown()) : null);

  async function request(url, controller = new win.AbortController()) {
    requests.add(controller);
    const timeout = win.setTimeout(() => controller.abort(), 10_000);
    try { return await helpers.fetchEspnJson(win, url, controller.signal); }
    finally { win.clearTimeout(timeout); requests.delete(controller); }
  }

  function readLocation() {
    const params = new URLSearchParams(win.location.search);
    selected = eventId(params.get('game')) ? params.get('game') : '';
    requestedMatchup = baseline.games.some((g) => g.id === params.get('matchup'))
      ? params.get('matchup') : '';
    pinned = Boolean(selected || requestedMatchup);
  }

  function saveLocation(replace = false) {
    const url = new URL(win.location.href);
    url.searchParams.delete('game'); url.searchParams.delete('matchup');
    if (selected) url.searchParams.set('game', selected);
    else if (requestedMatchup) url.searchParams.set('matchup', requestedMatchup);
    win.history[replace ? 'replaceState' : 'pushState'](null, '', url.pathname + url.search + url.hash);
  }

  function resolveSelection() {
    if (requestedMatchup) {
      const game = selectedKnown();
      const id = game && (observed(game)?.id || game.espnId);
      if (id && id !== selected) { selected = id; saveLocation(true); }
    }
    if (!pinned) {
      const me = doc.querySelector('[data-me-select]')?.value;
      const picks = baseline.entrants.find((e) => e.slug === me)?.teams || [];
      const game = chooseLiveGame(slate(), picks);
      if (game) { selected = game.id || ''; requestedMatchup = game.matchup || ''; }
    }
  }

  function renderRail() {
    $('[data-live-slate-title]').textContent = currentWindow()?.label || 'Games';
    const rail = $('[data-live-game-rail]');
    const previous = new Map(Array.from(rail.children, (el) => [el.dataset.key, el]));
    for (const [index, game] of slate().entries()) {
      const key = game.id || game.matchup;
      let button = previous.get(key);
      if (!button) {
        button = node('button', 'live-game-tile'); button.type = 'button';
        button.dataset.key = key;
        button.append(node('span', 'live-tile-status'), node('span', 'live-tile-score'));
      }
      previous.delete(key);
      button.dataset.event = game.id || ''; button.dataset.matchup = game.matchup || '';
      button.classList.toggle('is-playing', game.state === 'in');
      button.setAttribute('aria-pressed', String(Boolean(game.id && game.id === selected)
        || Boolean(game.matchup && game.matchup === requestedMatchup)));
      button.firstChild.textContent = game.state === 'pre' ? stamp(Date.parse(game.date))
        : game.status || game.clock || 'Final';
      button.lastChild.textContent = `${game.away} ${game.scoresAvailable ? game.awayScore : '—'}  ·  ${game.home} ${game.scoresAvailable ? game.homeScore : '—'}`;
      place(rail, button, index);
    }
    for (const el of previous.values()) el.remove();
  }

  function renderBoard() {
    const board = livePoolStandings(baseline, [...events.values()], now());
    const list = $('[data-live-standings]');
    const existing = new Map(Array.from(list.querySelectorAll('[data-entrant]'), (el) => [el.dataset.entrant, el]));
    if (!existing.size) list.replaceChildren();
    for (const [index, row] of board.rows.entries()) {
      let li = existing.get(row.slug);
      if (!li) {
        li = node('li'); li.dataset.entrant = row.slug;
        const name = node('a'); name.href = `${root.dataset.entrantBase}${row.slug}/`;
        li.append(name, node('span', 'live-gain'), node('strong'));
      }
      existing.delete(row.slug);
      li.classList.toggle('is-me', doc.querySelector('[data-me-select]')?.value === row.slug);
      const movement = row.bankedRank - row.rank;
      li.firstChild.textContent = `${row.rank}. ${row.name}${movement ? ` ${movement > 0 ? '↑' : '↓'}${Math.abs(movement)}` : ''}`;
      li.firstChild.title = movement ? `${Math.abs(movement)} place${Math.abs(movement) === 1 ? '' : 's'} ${movement > 0 ? 'up' : 'down'} from official standings` : 'Same rank as official standings';
      li.children[1].textContent = row.delta ? `+${points(row.delta)}` : '—';
      li.lastChild.textContent = points(row.total);
      place(list, li, index);
    }
    for (const li of existing.values()) li.remove();
    $('[data-live-board-status]').textContent = `${board.contributing} game${board.contributing === 1 ? '' : 's'} contributing. `
      + (board.missing ? `${board.missing} game${board.missing === 1 ? '' : 's'} awaiting scores. ` : '')
      + `Official baseline: ${stamp(Date.parse(baseline.generated))}.`
      + (baselineUnavailable ? ' Official refresh unavailable; retaining this baseline.' : '');
  }

  function renderGame() {
    const game = selectedEvent();
    if (!game) {
      $('[data-live-game-status]').textContent = selected ? 'Loading game…' : 'No matchup available';
      $('[data-live-scoreboard]').replaceChildren(); delete $('[data-live-scoreboard]').dataset.teams;
      $('[data-live-situation-text]').textContent = ''; $('[data-live-venue]').textContent = '';
      renderField(null);
      $('[data-live-stakes]').textContent = 'Choose a matchup to see the stakes.';
      $('[data-live-espn]').href = selected ? `https://www.espn.com/nfl/game/_/gameId/${selected}` : 'https://www.espn.com/nfl/scoreboard';
      return;
    }
    $('[data-live-game-status]').textContent = game.state === 'pre'
      ? `Kickoff ${stamp(Date.parse(game.date))}` : game.status || game.clock || 'Final';
    $('[data-live-espn]').href = selected ? `https://www.espn.com/nfl/game/_/gameId/${selected}` : 'https://www.espn.com/nfl/scoreboard';
    const scoreboard = $('[data-live-scoreboard]');
    const teamsKey = `${game.away}-${game.home}`;
    if (scoreboard.dataset.teams !== teamsKey) {
      scoreboard.replaceChildren(); scoreboard.dataset.teams = teamsKey;
      for (const team of [game.away, game.home]) {
        const side = node('div', 'live-score-side');
        side.append(chip(team), node('strong', 'live-big-score', '—')); scoreboard.append(side);
      }
    }
    [game.awayScore, game.homeScore].forEach((score, i) => {
      scoreboard.children[i].lastChild.textContent = game.scoresAvailable ? score : '—';
      scoreboard.children[i].classList.toggle('has-possession', game.state === 'in'
        && game.possession === [game.away, game.home][i]);
    });
    $('[data-live-situation-text]').textContent = game.state === 'in'
      ? [game.possession ? `${game.possession} ball` : '', game.down, game.redZone ? 'RED ZONE' : ''].filter(Boolean).join(' · ') : '';
    $('[data-live-venue]').textContent = [game.venue, game.network].filter(Boolean).join(' · ');
    renderField(game);
    const stakes = $('[data-live-stakes]'); stakes.replaceChildren();
    const known = selectedKnown();
    if (!known) stakes.textContent = game.seasonType === 1 ? 'Preseason games do not score pool points.' : 'Pool impact is awaiting a matching schedule entry.';
    else for (const team of [known.away, known.home]) {
      const owners = baseline.entrants.filter((e) => e.teams.includes(team));
      const gains = !known.scored && owners.length ? known.points[owners[0].slug][team] : null;
      const p = node('p'); p.append(chip(team), node('span', '',
        `${owners.length ? owners.map((e) => e.name).join(', ') : 'No owners in this pool'}${gains !== null ? ` · ${points(gains)} points each with a win` : known.scored ? ' · included in official standings' : ''}`)); stakes.append(p);
    }
  }

  function renderField(game) {
    const field = liveFieldPosition(game, helpers.normalizeEspnTeam);
    for (const selector of ['[data-live-field]', '[data-live-field-head]', '[data-live-field-legend]']) $(selector).hidden = !field;
    $('[data-live-field-label]').textContent = field ? game.down
      : 'Field position will appear when ESPN reports the next down and ball spot.';
    if (!field) return;
    const name = (team) => team === game.away ? game.awayName || team : game.homeName || team;
    const attack = field.direction === 1 ? 'right' : 'left';
    $('[data-live-field]').setAttribute('aria-label',
      `${name(game.possession)} ball, attacking ${attack}. ${game.down}. `
      + `${field.first === null ? '' : `${field.goalToGo ? 'Goal line' : 'First down'}: ${field.target}. `}${field.toGoal} yards to the end zone.`);
    for (const [selector, team] of [['[data-live-away-end]', game.away], ['[data-live-home-end]', game.home]]) {
      const end = $(selector);
      end.setAttribute('style', chipTemplates.get(team)?.getAttribute('style') || '');
      end.querySelector('text').textContent = name(team).toUpperCase();
    }
    const possessionChip = $('[data-live-possession-chip]');
    if (possessionChip.dataset.team !== game.possession) {
      possessionChip.replaceChildren(chip(game.possession)); possessionChip.dataset.team = game.possession;
    }
    $('[data-live-possession-name]').textContent = `${name(game.possession)} ball`;
    $('[data-live-direction]').dataset.direction = attack;
    $('[data-live-direction-arrow]').textContent = field.direction === 1 ? '→' : '←';
    $('[data-live-direction-text]').textContent = `Driving ${attack}`;
    const x = (position) => 100 + position * 10;
    $('[data-live-scrimmage]').style.transform = `translateX(${x(field.ball)}px)`;
    $('[data-live-ball]').style.transform = `translate(${x(field.ball)}px, 266.67px)`;
    $('[data-live-attack-arrow]').style.transform = `translate(${Math.max(155, Math.min(1045, x(field.ball)))}px, 355px) scaleX(${field.direction})`;
    // SVG elements do not support HTML's hidden property.
    $('[data-live-first-down]').style.display = field.first === null ? 'none' : '';
    if (field.first !== null) $('[data-live-first-down]').style.transform = `translateX(${x(field.first)}px)`;
    $('[data-live-spot]').textContent = field.spot;
    $('[data-live-target]').hidden = field.first === null;
    $('[data-live-target-text]').textContent = field.goalToGo ? 'Goal line' : `1st down: ${field.target}`;
    $('[data-live-goal-distance]').textContent = `${field.toGoal} ${field.toGoal === 1 ? 'yard' : 'yards'} to goal`;
  }

  function table(caption, headings, rows) {
    const wrap = node('div', 'live-table-wrap'); const t = node('table', 'live-stats-table');
    t.append(node('caption', '', caption));
    const head = node('thead'); const tr = node('tr');
    for (const text of headings) { const th = node('th', '', text); th.scope = 'col'; tr.append(th); }
    head.append(tr); t.append(head); const body = node('tbody');
    for (const row of rows) { const r = node('tr'); row.forEach((text, i) => {
      const cell = node(i ? 'td' : 'th', '', text ?? '—'); if (!i) cell.scope = 'row'; r.append(cell);
    }); body.append(r); }
    t.append(body); wrap.append(t); return wrap;
  }

  function renderSummary() {
    const cached = summaries.get(selected);
    if (cached?.data === renderedSummary) return;
    const old = renderedSummary; renderedSummary = cached?.data || null;
    const data = renderedSummary;
    const sameGame = data && old?.event.id === data.event.id;
    const tableScroll = new Map(Array.from(root.querySelectorAll('.live-table-wrap'),
      (el) => [el.querySelector('caption').textContent, el.scrollLeft]));
    const containers = ['[data-live-quarters]', '[data-live-scoring]', '[data-live-team-stats]', '[data-live-player-stats]'];
    for (const selector of containers) $(selector).replaceChildren();
    const drivesRoot = $('[data-live-drives]');
    if (!sameGame) { drivesRoot.replaceChildren(); $('[data-live-play-notice]').textContent = ''; }
    if (!data) {
      for (const selector of ['[data-live-scoring]', '[data-live-player-stats]', '[data-live-drives]']) {
        $(selector).append(node(selector.includes('scoring') ? 'li' : 'p', 'live-empty', 'Game details will appear when available.'));
      }
      return;
    }
    const count = Math.max(0, ...data.quarters.map((q) => q.scores.length));
    if (count) $('[data-live-quarters]').append(table('Quarter scoring', ['Team', ...Array.from({ length: count }, (_, i) => i > 3 ? `OT${i > 4 ? i - 3 : ''}` : `Q${i + 1}`)], data.quarters.map((q) => [q.team, ...Array.from({ length: count }, (_, i) => q.scores[i] ?? '—')])));
    for (const play of data.scoring) {
      const li = node('li'); li.append(node('b', '', `${phaseClock(play)} · ${data.event.away} ${play.awayScore} – ${data.event.home} ${play.homeScore}`), node('p', '', play.text)); $('[data-live-scoring]').append(li);
    }
    if (!data.scoring.length) $('[data-live-scoring]').append(node('li', 'live-empty', 'No scoring plays reported yet.'));
    const anchor = sameGame && Array.from(drivesRoot.querySelectorAll('.live-play')).find((el) => {
      const r = el.getBoundingClientRect(); return r.height && r.top >= 0 && r.top < win.innerHeight;
    });
    const anchorTop = anchor ? anchor.getBoundingClientRect().top : null;
    const previous = new Map(Array.from(drivesRoot.querySelectorAll('[data-drive]'), (el) => [el.dataset.drive, el]));
    for (const empty of drivesRoot.querySelectorAll('.live-empty')) empty.remove();
    for (const [index, drive] of data.drives.entries()) {
      let details = previous.get(drive.id);
      if (!details) { details = node('details', 'live-drive'); details.dataset.drive = drive.id; details.open = index === 0;
        details.append(node('summary'), node('ol')); }
      previous.delete(drive.id);
      details.firstChild.textContent = `${drive.team} · ${drive.result}${drive.yards != null ? ` · ${drive.yards} yards` : ''}${drive.duration ? ` · ${drive.duration}` : ''}`;
      const list = details.lastChild;
      const oldPlays = new Map(Array.from(list.children, (el) => [el.dataset.play, el]));
      for (const [playIndex, play] of drive.plays.entries()) {
        let li = oldPlays.get(play.id);
        if (!li) { li = node('li', 'live-play'); li.dataset.play = play.id; li.append(node('b'), node('p')); }
        oldPlays.delete(play.id);
        li.classList.toggle('is-scoring', play.scoring); li.classList.toggle('is-turnover', play.turnover);
        li.firstChild.textContent = `${phaseClock(play)}${play.scoring ? ' · SCORE' : play.turnover ? ' · TURNOVER' : ''}`;
        li.lastChild.textContent = play.text; place(list, li, playIndex);
      }
      for (const li of oldPlays.values()) li.remove();
      place(drivesRoot, details, index);
    }
    for (const el of previous.values()) el.remove();
    if (anchor?.isConnected) { const shift = anchor.getBoundingClientRect().top - anchorTop; if (shift) win.scrollBy(0, shift); }
    if (!data.drives.length) drivesRoot.append(node('p', 'live-empty', 'Play-by-play has not been reported yet.'));
    if (sameGame) {
      const oldIds = new Set(old.plays.map((p) => p.id)); const added = data.plays.filter((p) => !oldIds.has(p.id)).length;
      $('[data-live-play-notice]').textContent = added ? `${added} new play${added === 1 ? '' : 's'}. Newest drives appear first.` : '';
    }
    const metrics = [['totalYards', 'Total yards'], ['netPassingYards', 'Passing yards'], ['rushingYards', 'Rushing yards'], ['firstDowns', 'First downs'], ['thirdDownEff', 'Third downs'], ['turnovers', 'Turnovers'], ['possessionTime', 'Possession']];
    if (data.teamStats.length) $('[data-live-team-stats]').append(table('Team comparison', ['Stat', ...data.teamStats.map((t) => t.team)], metrics.map(([key, label]) => [label, ...data.teamStats.map((t) => t.stats[key])])));
    for (const group of data.playerStats) $('[data-live-player-stats]').append(table(`${group.team} ${group.name}`, ['Player', ...group.labels], group.athletes.map((a) => [a.name, ...a.stats])));
    if (!data.playerStats.length) $('[data-live-player-stats]').append(node('p', 'live-empty', 'Player stats have not been reported yet.'));
    if (sameGame) for (const el of root.querySelectorAll('.live-table-wrap')) {
      el.scrollLeft = tableScroll.get(el.querySelector('caption').textContent) || 0;
    }
  }

  function render() {
    renderRail(); renderBoard(); renderGame(); renderSummary();
    $('[data-live-detail-status]').textContent = detailState;
  }

  function scheduleDetails(event) {
    win.clearTimeout(detailTimer);
    const delay = liveRefreshDelay([event], 0, liveInterval);
    detailNextAt = now() + delay;
    if (delay) detailTimer = win.setTimeout(() => loadDetails(true), delay);
  }

  async function loadDetails(force = false) {
    if (!active() || !selected) return;
    if (detailController && requests.has(detailController) && !detailController.signal.aborted) return;
    const cached = summaries.get(selected);
    if (!force && cached?.data.event.completed && !cached.refresh) {
      detailState = `Plays and stats updated ${stamp(cached.at)}.`;
      $('[data-live-detail-status]').textContent = detailState;
      return;
    }
    if (!force && now() < detailNextAt) return;
    win.clearTimeout(detailTimer);
    detailController?.abort(); detailController = new win.AbortController();
    const controller = detailController; const generation = ++detailGeneration; const id = selected;
    detailState = cached ? detailState : 'Loading plays and stats…'; render();
    try {
      const data = parseLiveSummary(await request(`${ESPN_BASE}summary?event=${id}`, controller), helpers);
      if (generation !== detailGeneration || !active()) return;
      if (data.event.id !== id || data.event.seasonYear !== baseline.season) throw new Error('Unexpected game');
      summaries.set(id, { data, at: now() }); detailFailures = 0;
      detailState = `Plays and stats updated ${stamp(now())}.`;
      render();
      scheduleDetails(events.get(id) || data.event);
    } catch {
      if (generation !== detailGeneration || !active() || controller.signal.aborted && detailController !== controller) return;
      detailState = `Plays and stats unavailable.${cached ? ` Last update ${stamp(cached.at)}.` : ''} Retrying automatically.`;
      const delay = liveRefreshDelay([], ++detailFailures);
      detailNextAt = now() + delay;
      render(); detailTimer = win.setTimeout(() => loadDetails(true), delay);
    }
  }

  function scheduleNext() {
    win.clearTimeout(timer);
    if (!active()) return;
    const relevant = baseline.games.filter((g) => !g.scored && Date.parse(g.kickoff) <= now())
      .map((g) => observed(g)).filter(Boolean);
    const delay = liveRefreshDelay([...slate(), ...relevant], failures, liveInterval);
    // Even after all games finish, pick up the next official baseline.
    const baselineDue = Math.max(1000, BASELINE_INTERVAL - (now() - lastBaselineAttempt));
    timer = win.setTimeout(poll, delay ? Math.min(delay, baselineDue) : baselineDue);
  }

  async function poll() {
    if (!active() || running) return;
    running = true;
    let failed = false;
    try {
      if (now() - lastBaselineAttempt >= BASELINE_INTERVAL) {
        lastBaselineAttempt = now();
        try {
          const data = validateLiveBaseline(await request(root.dataset.baselineUrl));
          if (data.pool !== baseline.pool || data.season !== baseline.season) throw new Error('Different pool or season');
          if (Date.parse(data.generated) > Date.parse(baseline.generated)) baseline = data;
          baselineUnavailable = false;
        } catch { baselineUnavailable = true; }
      }
      const current = currentWindow();
      const known = selectedKnown();
      const wanted = baseline.windows.filter((w) => {
        const games = windowGames(w);
        const initial = !fetchedWindows.has(w.key)
          && (w.key === current?.key || games.some((g) => g.id === known?.id));
        return initial || games.some((g) => !g.scored
          && (w.key === current?.key || Date.parse(g.kickoff) <= now())
          && !observed(g)?.completed);
      });
      for (let i = 0; i < wanted.length && active(); i += 3) {
        await Promise.all(wanted.slice(i, i + 3).map(async (w) => {
          try {
            const payload = await request(liveScoreboardUrl(w));
            if (!Array.isArray(payload?.events)) throw new Error('Invalid scoreboard');
            const parsed = helpers.parseEspnScoreboard(payload);
            if (payload.events.length && !parsed.length) throw new Error('Invalid scoreboard');
            if (!active()) return;
            for (const event of parsed) {
              if (event.seasonYear !== baseline.season || !eventId(event.id)) continue;
              if (events.get(event.id)?.completed && !event.completed) continue;
              events.set(event.id, event);
            }
            fetchedWindows.add(w.key); lastScoreUpdate = now();
          } catch { failed = true; }
        }));
      }
      if (!active()) return;
      failures = failed ? failures + 1 : 0;
      doc.querySelector('[data-live-connection]').textContent = failed
        ? `Scores unavailable; retrying.${lastScoreUpdate ? ` Last update ${stamp(lastScoreUpdate)}.` : ''}`
        : lastScoreUpdate ? `Scores updated ${stamp(lastScoreUpdate)}` : 'Waiting for scores';
      const before = selected;
      resolveSelection();
      if (before !== selected) resetDetails();
      render();
      await loadDetails();
    } finally {
      running = false;
      if (refreshPending && active()) { refreshPending = false; poll(); }
      else scheduleNext();
    }
  }

  function resetDetails() {
    detailGeneration++; detailController?.abort(); win.clearTimeout(detailTimer);
    detailState = ''; detailFailures = 0; detailNextAt = 0;
  }
  function selectGame(id, matchup) {
    resetDetails();
    selected = id; requestedMatchup = matchup; pinned = true;
    saveLocation(); render(); loadDetails();
  }
  listen($('[data-live-game-rail]'), 'click', (event) => {
    const button = event.target.closest('[data-key]');
    if (button) selectGame(button.dataset.event, button.dataset.matchup);
  });
  function selectView(button) {
    for (const tab of root.querySelectorAll('[data-live-view]')) {
      const chosen = tab === button; tab.setAttribute('aria-selected', String(chosen)); tab.tabIndex = chosen ? 0 : -1;
      doc.getElementById(tab.getAttribute('aria-controls')).hidden = !chosen;
    }
  }
  listen($('[role="tablist"]'), 'click', (event) => {
    const button = event.target.closest('[data-live-view]'); if (button) selectView(button);
  });
  listen($('[role="tablist"]'), 'keydown', (event) => {
    const tabs = Array.from(root.querySelectorAll('[data-live-view]'));
    const index = tabs.indexOf(event.target);
    if (index < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    selectView(tabs[next]); tabs[next].focus();
  });
  const refresh = () => { fetchedWindows.clear(); resetDetails(); lastBaselineAttempt = -Infinity;
    if (summaries.has(selected)) summaries.get(selected).refresh = true;
    if (running) { refreshPending = true; return; }
    return poll(); };
  listen(doc.querySelector('[data-live-refresh]'), 'click', refresh);
  const fastRefresh = doc.querySelector('[data-live-fast-refresh]');
  const renderRefreshChoice = () => {
    const enabled = liveInterval === FAST_LIVE_INTERVAL;
    fastRefresh.setAttribute('aria-pressed', String(enabled));
    fastRefresh.querySelector('[data-live-fast-state]').textContent = enabled ? 'On' : 'Off';
  };
  renderRefreshChoice();
  listen(fastRefresh, 'click', () => {
    liveInterval = liveInterval === LIVE_INTERVAL ? FAST_LIVE_INTERVAL : LIVE_INTERVAL;
    try { win.localStorage.setItem(FAST_REFRESH_KEY, String(liveInterval === FAST_LIVE_INTERVAL)); }
    catch { /* Storage is optional; keep the choice for this visit. */ }
    renderRefreshChoice();
    if (!active()) return;
    // In-flight requests use the new interval when they finish. Leave failure
    // deadlines intact so changing the preference cannot bypass retry backoff.
    if (!running && !failures) scheduleNext();
    const cached = summaries.get(selected);
    if (cached && !detailFailures && !requests.has(detailController)) {
      scheduleDetails(events.get(selected) || cached.data.event);
    }
  });
  listen($('[data-live-copy]'), 'click', async () => {
    pinned = true; saveLocation(true);
    try { await win.navigator.clipboard.writeText(win.location.href); $('[data-live-share-status]').textContent = 'Game link copied.'; }
    catch { $('[data-live-share-status]').textContent = 'Copy the address from your browser to share this game.'; }
  });
  listen(win, 'popstate', () => {
    resetDetails(); readLocation(); resolveSelection(); render(); poll();
  });
  const suspend = () => {
    win.clearTimeout(timer); win.clearTimeout(detailTimer); detailGeneration++;
    for (const controller of requests) controller.abort();
  };
  const visibility = () => {
    if (active()) { poll(); loadDetails(true); }
    else { suspend(); doc.querySelector('[data-live-connection]').textContent = doc.hidden ? 'Updates paused while this tab is hidden.' : 'Offline · showing the last received scores.'; }
  };
  listen(doc, 'visibilitychange', visibility); listen(win, 'online', visibility); listen(win, 'offline', visibility);
  listen(win, 'pagehide', suspend);
  listen(win, 'pageshow', visibility);
  const me = doc.querySelector('[data-me-select]');
  if (me) listen(me, 'change', () => {
    const before = selected; resolveSelection(); if (before !== selected) resetDetails();
    render(); loadDetails();
  });
  const tz = doc.querySelector('[data-tz-select]'); if (tz) listen(tz, 'change', render);
  readLocation(); resolveSelection(); render();
  const ready = poll();
  return { ready, refresh, destroy() { stopped = true; suspend(); for (const remove of listeners) remove(); } };
}
