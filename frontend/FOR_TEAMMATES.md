# Notes for Kritazya and Suyog from Ashirwad's side

Updated for `main` at `0dc6a34`, the browser simulation design. Everything here is on branch **`ashirwad`**, and nothing is merged.
The full plan is `frontend/PLAN.md`.

## What I'm building (ASHIRWAD.md)
- **Simulation and hub, in the browser:** `frontend/src/sim/` and `frontend/src/hub/`, running in the `/sim` tab. It speaks the hub protocol (CONTRACTS.md §8) on `/ws/hub`.
- **Every screen:** charts read SpacetimeDB rows only; the Simulation view reads only `useDevices()`.
- **The catalog:** `backend/data/equipment_catalog.json`.
- **Static Web Apps:** the `infra/` files.

I build only against `contracts/fixtures/` and touch no file outside my scope.

## Suyog: where we meet later
- **`/ws/hub`:** my `src/hub/link.ts` and your `runtime/hub_link.py`. We both build against `contracts/fixtures/hub_protocol/`, so they should agree byte for byte.
  - My side follows §8 exactly: `hub_hello`; handles `hub_welcome` (including `host_taken`), `sim_build`, `sim_tick` (including `replay`) and `sim_control`; replies `hub_report` with the same `tick_id`.
- **REST and viewer `/ws`:** my `useApi()` and `/ws` fallback follow CONTRACTS.md §2 and the `rest/` and `ws/` fixtures.
  - Surge buttons use the SpacetimeDB `request_surge` reducer.
  - With `LIVE_TRANSPORT=ws` they call `POST /api/events/customers`.
- **First integration run (when the team decides):**
  - your API with `KITCHEN_IMPL=fake`;
  - my `/sim` tab pointed at your `/ws/hub`;
  - my viewer tabs on `LIVE_TRANSPORT=ws`.
- **CORS:** please allow the Static Web Apps origin; I'll send the URL once it's deployed.

## Kritazya: contract questions
These are kept as written until you answer them. The full list is in PLAN.md §7.
- **Q1, Proof data:** `BacktestResult` has no savings columns, busiest-day series, sensitivity rows or replay series. UI.md asks for all four, and the browser may not compute them. What shape will carry them?
- **Q2, Context strip:** UI.md asks for "next hours" and a price sparkline, but `live_context` only has summary strings. Should the strip read `GET /api/context`, or will `live_context` gain hourly columns?
- **Q3, Reconnect replay:** the hub "answers only the last replayed tick", but it can't tell which replayed tick is the last. What's the cue?
- **Q4, Tariff list:** there's no tariff list endpoint. The Builder fixes `demo_tariff_v1` for now.
- **Q5, Owner on the graph:** `owner` isn't an AgentLog agent name. Should owner actions appear on the Agent Network graph?
- **Q6, Missing docs:** CLAUDE.md points to `docs/TIMELINE.md` and `docs/DECISIONS.md`, which are gone. Where do gates and merge order live now?
- **Q7, Base branch:** `architecture-separation` doesn't exist on GitHub. Is `main` at `0dc6a34` the base to branch from?
- **SpacetimeDB bindings:** when they exist, I'll swap them in behind `useLive()`. No screen changes.

## Housekeeping
My old Python simulation (`backend/engine/{devices,hub,customers,fake_hub}.py`, `backend/tests/simulation/`) exists only on `ashirwad`.
It's now outside my scope and replaced by the TypeScript simulation. I plan to delete it from my branch, so nothing lands in `backend/engine/` when we merge.
