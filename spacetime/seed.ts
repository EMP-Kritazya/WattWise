// Seed a published WattWise database with the fixture rows (contracts/fixtures/spacetime/tables/), through the same
// reducers the runtime calls, so the frontend can be built against real tables before the runtime exists.
//
//   SPACETIME_URI=http://localhost:3000 SPACETIME_DB=wattwise SPACETIME_TOKEN=<runtime identity token> npm run seed
//
// The token must be the publisher's (runtime) identity: every state reducer checks it. FIXTURE DATA: not measured.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

type Row = Record<string, unknown>;

const here = dirname(fileURLToPath(import.meta.url));
const tablesDir = join(here, '..', 'contracts', 'fixtures', 'spacetime', 'tables');
const uri = (process.env.SPACETIME_URI ?? 'http://localhost:3000').replace(/\/$/, '');
const db = process.env.SPACETIME_DB ?? 'wattwise';
const token = process.env.SPACETIME_TOKEN;

const table = (name: string): Row[] => JSON.parse(readFileSync(join(tablesDir, `${name}.json`), 'utf8')) as Row[];
const cj = (o: unknown): string => JSON.stringify(o);
/** SATS-JSON option: { some: v } / { none: [] } (the HTTP API encodes Option as a sum type). */
const opt = (v: unknown): unknown => (v === null || v === undefined ? { none: [] } : { some: v });

async function call(reducer: string, args: unknown[]): Promise<void> {
  const res = await fetch(`${uri}/v1/database/${db}/call/${reducer}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(args),
  });
  if (!res.ok) throw new Error(`${reducer}: HTTP ${res.status} ${await res.text()}`);
}

async function main(): Promise<void> {
  await call('reset_all', []);

  const clock = table('live_clock')[0];
  await call('set_clock', [
    clock.playing, clock.speed, clock.sim_ts, clock.tick_id, opt(clock.paused_reason),
    clock.day_index, clock.run_days, clock.phase, clock.sim_host,
  ]);

  // publish_ticks takes one tick pair per call: replay tick_history pairwise, the final call carries the live rows.
  const history = table('tick_history');
  const ticks = table('live_tick');
  const devices = table('live_device');
  const { id: _id, ...comparison } = table('live_comparison')[0];
  for (let i = 0; i + 1 < history.length; i += 2) {
    const pair = [history[i], history[i + 1]];
    const liveTick = ticks.map(tk => ({ ...tk, ts: pair[0].ts }));
    const last = i + 2 >= history.length;
    await call('publish_ticks', [cj({
      live_tick: last ? ticks : liveTick,
      tick_history: pair,
      live_device: devices,
      live_comparison: { id: 0, ...comparison },
    })]);
  }

  for (const row of table('live_feed')) await call('publish_feed', [cj(row)]);
  for (const row of table('live_context')) await call('publish_context', [cj(row)]);
  for (const row of table('live_escalation')) await call('publish_escalation', [cj(row)]);
  for (const { id: _logId, ...row } of table('live_agent_log')) await call('log_agent', [cj(row)]);

  const points = table('backtest_point');
  if (points.length) await call('reset_backtest', [points[0].run_id]);
  for (const row of points) await call('publish_backtest_point', [cj(row)]);
  for (const row of table('backtest_month')) await call('publish_backtest_month', [cj(row)]);

  for (const row of table('surge_request')) await call('request_surge', [row.customers, row.duration_min]);
  console.log(`seeded ${db} at ${uri} from ${tablesDir} (fixture data, not measured)`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
