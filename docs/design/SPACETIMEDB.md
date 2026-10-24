# Design: SpacetimeDB — the live shared kitchen (owner: Kritazya)

SpacetimeDB is what ticks: every viewer and judge sees and plays in the same kitchen in real time. Module in TypeScript
(`spacetime/`); Python writes through `backend/live/spacetime_client.py`; browsers subscribe with generated bindings.

## Principles
1. **Mirror, don't decide.** The engine is the truth; reducers only validate and write. No math, randomness or clock reads.
2. **Runtime writes state; viewers write requests.** State tables are written only by the runtime identity (checked against
   the identity stored at `init`). Viewers may call public **request** reducers (`request_surge`) whose rows the runtime consumes.
   This is the "many users writing at once" the SpacetimeDB track asks for.
3. **Batch per tick.** One `publish_ticks` call per real tick for both lanes. Never one call per device.
4. **Bounded tables.** Current state + short history (tick_history 180 sim min per lane, feed 50, escalations 20, agent log 300).
   Durable history belongs in Convex.
5. **Schema on day one.** Automatic migrations allow adding tables but block most changes to existing ones; agree the schema in
   Phase 1, then only add. Breaking change → republish with data cleared (dev only), tell the team.
6. **Generated bindings only** (`spacetime generate`), never hand-edited.
7. **Design for the screens' queries:** keys and indexes by lane and time, newest first.
8. **Fallback exists.** `LIVE_TRANSPORT=ws` sends the same messages over FastAPI `/ws`; the UI hook switches automatically.

## Tables and reducers
CONTRACTS.md section 5 (`live_tick`, `tick_history`, `live_device`, `live_comparison`, `live_feed`, `live_clock`,
`live_context`, `live_escalation`, `live_agent_log`, `surge_request`; reducers `publish_ticks`, `publish_feed`, `set_clock`,
`publish_context`, `publish_escalation`, `log_agent`, `reset_all`, `request_surge`, `consume_surge`, scheduled `prune`).

## Python client (`backend/live/spacetime_client.py`)
- Calls reducers over HTTP: `POST /v1/database/<db>/call/<reducer>` with a JSON array of arguments and the runtime identity's
  bearer token. Verify against the installed SpacetimeDB version in Phase 1 (first task) and record it in DECISIONS.md.
- Reads new surge requests through the SQL endpoint each tick.
- Never blocks the run loop: a bounded queue keeps the latest tick (drop older ticks), never drops feed, escalations or agent log.
- `fakes/fake_live.py` + `spacetime/seed.ts` write plausible rows so the frontend can build before the runtime exists.

## Throughput
120×: ~2 real ticks/s, one batched call each, ~25 device rows. Comfortable; the queue absorbs spikes.

## Hosting
SpacetimeDB's hosted cloud (Maincloud). If Microsoft requires everything on Azure, run it standalone in a Container App with a volume.
