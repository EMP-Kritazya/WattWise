// Module unit tests on SpacetimeDB's in-process test datastore (spacetimedb/server/test-utils): every reducer fed the
// exact fixture arguments (contracts/fixtures/spacetime/reducers/*.json) writes rows equal to the fixture tables
// (contracts/fixtures/spacetime/tables/*.json); the runtime identity check, the public request reducer and the table
// bounds hold. This runs the real module code without the `spacetime` CLI.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, test } from 'vitest';
import { ConnectionId } from 'spacetimedb';
import { createModuleTestHarness, TestAuth } from 'spacetimedb/server/test-utils';
import spacetimedb, * as mod from '../src/index';

type Row = Record<string, unknown>;
const FIX = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'contracts', 'fixtures', 'spacetime');
const reducerFixture = (name: string): { reducer: string; args: unknown[] } =>
  JSON.parse(readFileSync(join(FIX, 'reducers', `${name}.json`), 'utf8'));
const tableFixture = (name: string): Row[] => JSON.parse(readFileSync(join(FIX, 'tables', `${name}.json`), 'utf8'));
const rowsStream = (): Row[] =>
  readFileSync(join(FIX, 'rows_stream.jsonl'), 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));

/** Table rows as plain JSON (options undefined -> null), keyed order irrelevant. */
const plain = (rows: Iterable<Row>): Row[] =>
  [...rows].map(r => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v === undefined ? null : v])));

const byKey = (rows: Row[], key: string) => [...rows].sort((a, b) => String(a[key]).localeCompare(String(b[key])));

const harness = () => createModuleTestHarness(spacetimedb, mod);
let h: ReturnType<typeof harness>;
const runtime = TestAuth.internal(); // sender = module identity = the publisher in these tests
const viewer = () =>
  TestAuth.fromJwtPayload(JSON.stringify({ iss: 'https://judge.example', sub: 'phone-1' }), ConnectionId.random());

// Call a reducer export as the host would, with positional fixture args mapped onto the declared parameter names.
const PARAMS: Record<string, string[]> = {
  publish_ticks: ['payload_json'],
  publish_feed: ['decision_json'],
  publish_context: ['context_json'],
  publish_escalation: ['escalation_json'],
  log_agent: ['agent_log_json'],
  publish_backtest_point: ['point_json'],
  publish_backtest_month: ['month_json'],
  reset_backtest: ['run_id'],
  reset_all: [],
  consume_surge: ['id'],
  request_surge: ['customers', 'duration_min'],
  set_clock: ['playing', 'speed', 'sim_ts', 'tick_id', 'paused_reason', 'day_index', 'run_days', 'phase', 'sim_host'],
};

function call(name: string, args: unknown[], auth = runtime): void {
  const names = PARAMS[name];
  const obj = Object.fromEntries(names.map((n, i) => [n, args[i] === null ? undefined : args[i]]));
  const fn = (mod as unknown as Record<string, (ctx: unknown, a: unknown) => void>)[name];
  h.withReducerTx(auth, ctx => fn(ctx, obj));
}

const callFixture = (name: string, auth = runtime) => call(name, reducerFixture(name).args, auth);

beforeEach(() => {
  h = harness();
  h.withReducerTx(runtime, ctx => mod.init(ctx, {}));
});

describe('fixture reducer args write the fixture rows', () => {
  test('publish_ticks', () => {
    callFixture('publish_ticks');
    expect(byKey(plain(h.db.live_tick.iter()), 'lane')).toEqual(byKey(tableFixture('live_tick'), 'lane'));
    expect(byKey(plain(h.db.live_device.iter()), 'key')).toEqual(byKey(tableFixture('live_device'), 'key'));
    // The recording predates saved_month_usd (2026-10-25, optional), so its column is null.
    expect(plain(h.db.live_comparison.iter())).toEqual(tableFixture('live_comparison').map(r => ({ ...r, saved_month_usd: null })));
    const last2 = tableFixture('tick_history').slice(-2).map(r => ({ key: `${r.lane}:${r.ts}`, ...r }));
    expect(byKey(plain(h.db.tick_history.iter()), 'key')).toEqual(byKey(last2, 'key'));
  });

  test('publish_feed / publish_context / publish_escalation / set_clock', () => {
    callFixture('publish_feed');
    expect(plain(h.db.live_feed.iter())).toEqual([tableFixture('live_feed')[0]]);
    callFixture('publish_context');
    expect(plain(h.db.live_context.iter())).toEqual(tableFixture('live_context'));
    callFixture('publish_escalation');
    expect(plain(h.db.live_escalation.iter())).toEqual(tableFixture('live_escalation'));
    callFixture('set_clock');
    expect(plain(h.db.live_clock.iter())).toEqual(tableFixture('live_clock'));
  });

  test('log_agent appends with an auto id', () => {
    callFixture('log_agent');
    expect(plain(h.db.live_agent_log.iter())).toEqual([tableFixture('live_agent_log')[0]]);
  });

  test('backtest point / month upsert; reset_backtest clears the previous run', () => {
    callFixture('publish_backtest_point');
    callFixture('publish_backtest_month');
    const point = JSON.parse(reducerFixture('publish_backtest_point').args[0] as string);
    const month = JSON.parse(reducerFixture('publish_backtest_month').args[0] as string);
    expect(plain(h.db.backtest_point.iter())).toEqual([point]);
    expect(plain(h.db.backtest_month.iter())).toEqual([month]);
    expect(tableFixture('backtest_point')).toContainEqual(point);
    expect(tableFixture('backtest_month')).toContainEqual(month);
    callFixture('reset_backtest');
    expect([...h.db.backtest_point.iter()]).toHaveLength(0);
    expect([...h.db.backtest_month.iter()]).toHaveLength(0);
  });

  test('every fixture backtest row loads; a new run id replaces the old run', () => {
    for (const r of tableFixture('backtest_point')) call('publish_backtest_point', [JSON.stringify(r)]);
    for (const r of tableFixture('backtest_month')) call('publish_backtest_month', [JSON.stringify(r)]);
    expect(byKey(plain(h.db.backtest_point.iter()), 'key')).toEqual(byKey(tableFixture('backtest_point'), 'key'));
    expect(byKey(plain(h.db.backtest_month.iter()), 'key')).toEqual(byKey(tableFixture('backtest_month'), 'key'));
    const next = { ...tableFixture('backtest_point')[0], run_id: 'run_0002', key: 'run_0002:2026-06-01' };
    call('publish_backtest_point', [JSON.stringify(next)]);
    expect(plain(h.db.backtest_point.iter())).toEqual([next]);
    expect([...h.db.backtest_month.iter()]).toHaveLength(0);
  });

  test('surges: anyone requests, the runtime consumes', () => {
    callFixture('request_surge', viewer());
    const [row] = plain(h.db.surge_request.iter());
    expect(row).toMatchObject({ id: 1, customers: 40, duration_min: 60, consumed: false });
    expect(typeof row.requested_by).toBe('string');
    callFixture('consume_surge');
    expect(plain(h.db.surge_request.iter())[0].consumed).toBe(true);
    expect(() => call('request_surge', [81, 60], viewer())).toThrow();
    expect(() => call('request_surge', [10, 14], viewer())).toThrow();
    expect(() => call('request_surge', [10, 121], viewer())).toThrow();
  });

  test('reset_all clears live tables', () => {
    callFixture('publish_ticks');
    callFixture('publish_feed');
    callFixture('set_clock');
    callFixture('reset_all');
    for (const t of ['live_tick', 'tick_history', 'live_device', 'live_comparison', 'live_feed', 'live_clock'] as const) {
      expect([...(h.db as any)[t].iter()]).toHaveLength(0);
    }
  });
});

describe('runtime identity only', () => {
  test('a viewer cannot write state', () => {
    for (const name of Object.keys(PARAMS)) {
      if (name === 'request_surge') continue;
      if (name === 'consume_surge') callFixture('request_surge', viewer());
      expect(() => callFixture(name, viewer()), name).toThrow(/runtime identity only/);
    }
  });

  test('malformed payloads are refused', () => {
    expect(() => call('publish_ticks', ['not json'])).toThrow();
    expect(() => call('publish_ticks', [JSON.stringify({ live_tick: [], tick_history: [], live_device: [] })])).toThrow();
    const bad = JSON.parse(reducerFixture('publish_feed').args[0] as string);
    bad.lane = 'other';
    expect(() => call('publish_feed', [JSON.stringify(bad)])).toThrow();
  });
});

describe('bounded tables', () => {
  test('rows_stream: tick_history keeps the last 180 sim minutes per lane, live rows are the latest tick', () => {
    const frames = rowsStream();
    for (const f of frames) call('publish_ticks', [JSON.stringify(f)]);
    const hist = plain(h.db.tick_history.iter());
    // 120 ticks < 180 min: every tick kept, both lanes
    expect(hist).toHaveLength(2 * frames.length);
    const last = frames[frames.length - 1];
    expect(byKey(plain(h.db.live_tick.iter()), 'lane')).toEqual(byKey(last.live_tick as Row[], 'lane'));
    // 200 more minutes on one lane: only the last 180 (ts > latest − 180 min) stay
    const base = Date.parse('2026-07-19T00:00:00Z');
    for (let i = 0; i < 200; i++) {
      const ts = new Date(base + i * 60_000).toISOString().replace('.000Z', 'Z');
      const f = structuredClone(last) as any;
      f.tick_history = [{ lane: 'without', ts, total_kw: 1, block_avg_kw: 1 }, { lane: 'with', ts, total_kw: 1, block_avg_kw: 1 }];
      call('publish_ticks', [JSON.stringify(f)]);
    }
    const without = plain(h.db.tick_history.iter()).filter(r => r.lane === 'without');
    expect(without).toHaveLength(180);
  });

  test('feed keeps the last 50 decisions by id number (d_9999 < d_10000)', () => {
    const row = JSON.parse(reducerFixture('publish_feed').args[0] as string);
    for (let i = 9960; i < 10020; i++) call('publish_feed', [JSON.stringify({ ...row, decision_id: `d_${String(i).padStart(4, '0')}` })]);
    const ids = plain(h.db.live_feed.iter()).map(r => Number(String(r.decision_id).slice(2))).sort((a, b) => a - b);
    expect(ids).toHaveLength(50);
    expect(ids[0]).toBe(9970);
  });

  test('escalations keep 20, agent log keeps 300', () => {
    const e = JSON.parse(reducerFixture('publish_escalation').args[0] as string);
    for (let i = 1; i <= 25; i++) call('publish_escalation', [JSON.stringify({ ...e, escalation_id: `e_${String(i).padStart(4, '0')}` })]);
    expect([...h.db.live_escalation.iter()]).toHaveLength(20);
    const log = reducerFixture('log_agent').args[0] as string;
    for (let i = 0; i < 305; i++) call('log_agent', [log]);
    const ids = plain(h.db.live_agent_log.iter()).map(r => r.id as number);
    expect(ids).toHaveLength(300);
    expect(Math.min(...ids)).toBe(6);
  });
});

describe('G73 escalation notices', () => {
  const row = () => ({
    ...tableFixture('live_escalation')[0],
    status: 'open', resolved_by: null,
    claude_attempts_json: JSON.stringify([{ ts: '2026-07-18T01:01:00Z', option_id: 'accept_overrun', accepted: false, reason: 'outside_authority', rationale: null }]),
    explanation: 'The engine rejected the choice; the safe fallback remains in force.',
    explanation_source: 'template',
  });

  test('persists attempts and notification source on upsert', () => {
    const notice = row();
    call('publish_escalation', [JSON.stringify(notice)]);
    expect(plain(h.db.live_escalation.iter())[0]).toEqual(notice);
    call('publish_escalation', [JSON.stringify({...notice, explanation: 'Claude explained the verdict.', explanation_source: 'ai'})]);
    expect(plain(h.db.live_escalation.iter())[0].explanation_source).toBe('ai');
  });

  test('rejects removed owner states and invalid notices atomically', () => {
    for (const patch of [
      {status: 'awaiting_owner'}, {resolved_by: 'owner'}, {explanation_source: 'owner'},
      {claude_attempts_json: '{}'}, {claude_attempts_json: '[{"accepted":false,"reason":"anything"}]'},
    ]) {
      expect(() => call('publish_escalation', [JSON.stringify({...row(), ...patch})])).toThrow();
      expect(plain(h.db.live_escalation.iter())).toEqual([]);
    }
  });
});
