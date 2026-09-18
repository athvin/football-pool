// @vitest-environment node
/** Live contract checks against the real ESPN API.
 *
 * Why these exist: ESPN stopped accepting date-range scoreboard queries
 * (dates=YYYYMMDD-YYYYMMDD now returns 400) and every live surface broke at
 * once — while the whole unit suite stayed green, because mocks accept
 * whatever URL the code builds. The mocked tests pin what *our* code sends
 * and how it reads a captured response; only a real request can notice ESPN
 * moving underneath both. So these tests hit the live endpoints with the
 * exact URLs the shipped builders produce and read the responses through the
 * shipped parsers — the same chain a visitor's browser runs.
 *
 * They are skipped unless ESPN_CONTRACT=1, keeping the default suite
 * hermetic and deploys independent of ESPN's uptime. The espn-contract
 * workflow runs them on a daily in-season schedule, so a contract change
 * fails a scheduled run instead of a Sunday. A failure here means "ESPN
 * changed or is down", not "this repo has a bug" — fix the builders and
 * parsers to match reality, then update the mocked tests to pin the new
 * shape.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { ESPN_BASE, liveOutcome, liveScoreboardUrl, matchLiveGame, parseLiveSummary } from '../../assets/live.js';
import { normalizeEspnTeam, parseEspnScoreboard, preseasonScoreboardUrl } from '../../assets/site.js';

const SEASON = Number(
  readFileSync(new URL('../../config.yaml', import.meta.url), 'utf8').match(/^active_season:\s*(\d+)/m)[1],
);
const TEAM = /^[A-Z]{2,3}$/;
const OPTS = { timeout: 30_000, retry: 1 };

async function get(url) {
  const response = await fetch(url);
  // The exact failure that motivated this file: a URL shape ESPN rejects.
  expect(response.ok, `${url} answered HTTP ${response.status}`).toBe(true);
  return response.json();
}

/** Every field the overlay reads from a scoreboard event, checked once. */
function expectWellFormed(event, seasonType) {
  expect(event.id).toMatch(/^\d+$/);
  expect(event.seasonType).toBe(seasonType);
  expect(event.away).toMatch(TEAM);
  expect(event.home).toMatch(TEAM);
  expect(event.away).not.toBe(event.home);
  expect(['pre', 'in', 'post']).toContain(event.state);
  expect(Number.isFinite(Date.parse(event.date))).toBe(true);
}

describe.runIf(process.env.ESPN_CONTRACT)('ESPN live contract', () => {
  test('the regular-season week query returns a full parseable slate', OPTS, async () => {
    const payload = await get(liveScoreboardUrl({ kind: 'REG', week: 1 }, SEASON));
    const events = parseEspnScoreboard(payload).filter((e) => e.seasonYear === SEASON);
    // Week 1 is published with the schedule in May, so this holds year round.
    expect(events.length).toBeGreaterThanOrEqual(14);
    for (const event of events) expectWellFormed(event, 2);
    for (const event of events) expect(event.week).toBe(1);

    // The overlay's matcher must find a baseline game in this response from
    // schedule facts alone — both by ESPN id and by phase-week agreement.
    const [first] = events;
    const game = { kind: 'REG', week: 1, away: first.away, home: first.home, date: '' };
    expect(matchLiveGame({ ...game, espnId: first.id }, events, SEASON)?.id).toBe(first.id);
    expect(matchLiveGame({ ...game, espnId: '' }, events, SEASON)?.id).toBe(first.id);

    // Once games have been played, their finals must settle: a completed
    // non-tie must name its winner, or live standings can never move.
    for (const event of events.filter((e) => e.completed && e.scoresAvailable)) {
      expect([event.away, event.home, 'TIE']).toContain(liveOutcome(event, 'REG'));
    }
  });

  test('the playoff week query form works for every round mapping', OPTS, async () => {
    // Last season's Wild Card round always exists and is always final.
    const payload = await get(liveScoreboardUrl({ kind: 'WC', week: 19 }, SEASON - 1));
    const events = parseEspnScoreboard(payload).filter((e) => e.seasonYear === SEASON - 1);
    expect(events.length).toBeGreaterThanOrEqual(6);
    for (const event of events) {
      expectWellFormed(event, 3);
      // matchLiveGame leans on ESPN numbering playoff rounds 1/2/3/5.
      expect(event.week).toBe(1);
      expect(event.completed).toBe(true);
      expect([event.away, event.home]).toContain(liveOutcome(event, 'WC'));
    }
  });

  test('the summary endpoint still carries what the Game Center renders', OPTS, async () => {
    const slate = parseEspnScoreboard(await get(liveScoreboardUrl({ kind: 'REG', week: 1 }, SEASON)))
      .filter((e) => e.seasonYear === SEASON);
    const payload = await get(`${ESPN_BASE}summary?event=${slate[0].id}`);
    const summary = parseLiveSummary(payload, { parseEspnScoreboard, normalizeEspnTeam });
    expect(summary.event.id).toBe(slate[0].id);
    expect(summary.event.seasonYear).toBe(SEASON);
    for (const key of ['drives', 'plays', 'quarters', 'teamStats', 'playerStats', 'scoring']) {
      expect(Array.isArray(summary[key])).toBe(true);
    }
  });

  test('the preseason year query yields that preseason and nothing else after filtering', OPTS, async () => {
    const games = parseEspnScoreboard(await get(preseasonScoreboardUrl(SEASON)))
      .filter((game) => game.seasonType === 1 && game.seasonYear === SEASON);
    // Hall of Fame game plus three full weekends.
    expect(games.length).toBeGreaterThanOrEqual(40);
    for (const game of games) expectWellFormed(game, 1);
  });
});
