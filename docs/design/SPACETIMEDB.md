# Design: SpacetimeDB — the live shared kitchen (owner: Kritazya)

SpacetimeDB is what ticks: every viewer and judge sees and plays in the same kitchen in real time. Module in TypeScript
(`spacetime/`); Python writes through `backend/live/spacetime_client.py`; browsers subscribe with generated bindings.

## Principles
1. **Mirror, don't decide.** The engine is the truth; reducers only validate and write. No math, randomness or clock reads.
2. **Runtime writes state; viewers write requests.** State tables are written only by the runtime identity (checked against
   the identity stored at `init`). Viewers may call public **request** reducers (`request_surge`) whose rows the runtime consumes.
   This is the "many users writing at once" the SpacetimeDB track asks for.
3. **Batch per tick.** One `publish_ticks` call per real tick for both lanes (overnight: once per closed 15-min block). Never one call per device.
4. **Bounded tables.** Current state + short history (tick_history 180 sim min per lane, feed 50, escalations 20, agent log 300).
   Durable history belongs in Convex.
5. **Schema on day one.** Automatic migrations allow adding tables but block most changes to existing ones; agree the schema in
   Phase 1, then only add. Breaking change → republish with data cleared (dev only), tell the team.
6. **Generated bindings only** (`spacetime generate`), never hand-edited.
7. **Design for the screens' queries:** keys and indexes by lane and time, newest first.
8. **Fallback exists.** `LIVE_TRANSPORT=ws` sends the same messages over FastAPI `/ws`; the UI hook switches automatically.
9. **Month to date lives here too.** For now everything runs in simulation (no physical ESP32), and the `live_tick` row per lane
   is the month-to-date store (month peaks, energy and cost so far). The engine seeds it from the ComStock warm-up; it is not read back
   in this build (`WarmUpHistory.month_to_date` stays null; `reset_all` clears it with the other tables).
10. **The UI's only live source.** Every screen in every tab (sim host included) draws from these tables: kitchen floor from
   `live_device` (state, power, physical gauges), energy and cost from `live_tick`, charts from `tick_history`. The browser
   simulation never writes here; it reports to FastAPI over `/ws/hub` and the runtime publishes.

## Tables and reducers
CONTRACTS.md section 5 (`live_tick`, `tick_history`, `live_device`, `live_comparison`, `live_feed`, `live_clock`,
`live_context`, `live_escalation`, `live_agent_log`, `surge_request`, `backtest_point`, `backtest_month`; reducers
`publish_ticks`, `publish_feed`, `set_clock`, `publish_context`, `publish_escalation`, `log_agent`, `publish_backtest_point`,
`publish_backtest_month`, `reset_backtest`, `reset_all`, `request_surge`, `consume_surge`, scheduled `prune`).

Module notes (`spacetime/src/index.ts`, SDK `spacetimedb` 2.13.0): `tick_history` stores its `lane` + `ts` key as one string
primary key `key = "<lane>:<ts>"` (an extra column in the generated row; the app drops it). Private tables `runtime_config`
(the identity stored at `init`) and `prune_schedule` (every 60 s). Bounds are applied on every write and again by `prune`.
`reset_all` clears the live tables only (not backtest rows or surge requests). Option arguments (`set_clock.paused_reason`)
travel over HTTP as SATS sums `{"some": v}` / `{"none": []}` (`SPACETIME_OPTION_ENCODING=null` sends plain null instead).
Unit tests run the module on SpacetimeDB's in-process test datastore (`cd spacetime && npm test`).

## Python client (`backend/live/spacetime_client.py`)
- Calls reducers over HTTP: `POST /v1/database/<db>/call/<reducer>` with a JSON array of arguments and the runtime identity's
  bearer token. Verify against the installed SpacetimeDB version in Phase 1 (first task) and record the result here.
  **Status 2026-10-24: NOT yet verified** (the `spacetime` CLI is not installed on the build machine). To verify:
  `curl -sSf https://install.spacetimedb.com | sh`, `spacetime start`, `cd spacetime && spacetime build && spacetime publish
  wattwise`, then `SPACETIME_TOKEN=$(spacetime login show --token) npm run seed` (exercises every reducer over HTTP, including
  the Option encoding) and record the version and result here.
- Reads new surge requests through the SQL endpoint each tick.
- Never blocks the run loop: a bounded queue keeps the latest tick (drop older ticks), never drops feed, escalations or agent log.
- `fakes/fake_live.py` + `spacetime/seed.ts` write plausible rows so the frontend can build before the runtime exists.

## Throughput
120×: ~2 real ticks/s, one batched call each, ~25 device rows. Comfortable; the queue absorbs spikes.

## Hosting
SpacetimeDB's hosted cloud (Maincloud). If Microsoft requires everything on Azure, run it standalone in a Container App with a volume.
