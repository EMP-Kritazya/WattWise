# ASHIRWAD.md — your working instructions (Frontend: UI + Simulation + Hub)

> **Claude Code: this file is Ashirwad's instruction set.** Read it first in every session, together with the golden rules
> in `CLAUDE.md`. When this file and a general doc disagree about *what Ashirwad builds or may touch*, this file wins.
> Anything about shared shapes is decided by `docs/CONTRACTS.md`; never change it from here.

**Branch:** `ashirwad` (create it from `architecture-separation` if it doesn't exist) · **Mission:** the kitchen behaves like a
real one, and everyone can see it.

## 1. Your job in one paragraph
You build everything in the browser. **The simulation** (appliances with their own React state, seeded customers, two lanes)
and **the hub** (the single ESP32-style controller every appliance reports to) run in the sim host tab (`/sim`). The hub
receives a `sim_tick` from FastAPI every tick (1 sim minute), applies any Commands to the appliances (their React state changes
and they re-render), steps the simulation one minute, and replies with a `hub_report` (each lane's state + acks). This is where
the engine's decisions become visible: Engine → Hub → Simulation, and Simulation → Hub → Engine. **The UI** shows it all: a
centred `Charts | Simulation` toggle, live charts from SpacetimeDB, the kitchen floor, decisions, escalations, chat.

## 2. Scope — exactly what you may edit
| You may create and edit | Never edit (read only) |
|---|---|
| `frontend/` (all of it: `src/sim/`, `src/hub/`, `src/screens/`, `src/data/`, `src/mocks/`, configs, tests) | `docs/` (all docs, including this file), `CLAUDE.md`, `README.md` |
| `backend/data/equipment_catalog.json` | `contracts/` (shapes, schema, **fixtures**) |
| `infra/` Static Web Apps files | `backend/` (everything except the catalog), `agents/`, `spacetime/`, `convex/`, `firmware/` |

## 3. Rules for this phase (independent development)
1. **Build only against the fake data** in `contracts/fixtures/` (section 5). Do not wait for, call, or import Suyog's API or
   Kritazya's SpacetimeDB/engine. Your app must run end to end with mocks alone.
2. **Do not merge** anything, open PRs to `main`, or pull teammates' branches into yours. Commit to `ashirwad` only.
3. **Do not change any structure you don't own**: no edits to contracts, fixtures, docs, folder layout or other people's code.
   If a shape looks wrong or missing, stop, keep the code matching the contract as written, and add it to a
   "Contract questions" list in your session summary for Kritazya.
4. **Never hand-edit fixtures.** Read them; if you need a different scenario, ask Kritazya to regenerate.
5. **Compute nothing in screens.** Energy, cost, peaks, savings, forecasts come from the engine (fixtures now, SpacetimeDB later).
   The simulation computes only physical power and state; the hub only sums power (`total_kw`) and `power_pct`.
6. **Determinism:** no `Math.random()` or `Date.now()` in `src/sim/` or `src/hub/`; one seeded PRNG per kitchen (seed from `sim_build`).

## 4. What to build (in order; tick when done and tested)
**A. Skeleton**
- [ ] Vite + React + TS + Tailwind + shadcn/ui + Recharts app; routes: Builder, Live, Agent Network, Proof, `/sim`
- [ ] Types for every shape you use, matching `docs/CONTRACTS.md` exactly (generated later; hand types now only in `src/types/`, marked `// STUB: replace with generated types`)
- [ ] `src/mocks/`: one switch (e.g. `VITE_MOCKS=1`) that serves REST, `/ws`, SpacetimeDB rows and the `/ws/hub` server from fixtures
- [ ] `src/data/` hooks: `useLive()` (SpacetimeDB tables; `/ws` fallback), `useDevices()` (section 6), `useApi()` (REST)

**B. Simulation + hub (`src/sim/`, `src/hub/`)** — design: `docs/design/SIMULATION.md`
- [ ] `equipment_catalog.json` with `default_limits` + `source_note` (FSTC / ENERGY STAR figures)
- [ ] Appliance interface (`step`, `reading`, `apply`, CONTRACTS.md §9); power models fixed, cycling, demand_driven, job (thermal if time)
- [ ] Appliances hold state in React (one store per kitchen lane); applying a Command updates state and re-renders
- [ ] Seeded customers × `inputs.crowd_multiplier` + `surges`; both lanes see the same customers
- [ ] Hub: per tick apply Commands → step 1 minute → HubReport per lane (`total_kw` exact sum, `power_pct`, `physical`, `acks`)
- [ ] `src/hub/link.ts`: `/ws/hub` protocol (CONTRACTS.md §8): `hub_hello`, handle `hub_welcome` (incl. `host_taken`), `sim_build`, `sim_tick`, `sim_control`; send `hub_report` every tick

**C. Screens** — design: `docs/design/UI.md`
- [ ] Kitchen Builder: equipment counts (0–5), importance + limits per unit, **peak goal** `Minimize peak | Hard limit` (+ kW), location, preferences, Claude's authority
- [ ] Live screen with the centred **`Charts | Simulation` toggle**: Charts view (two-lane chart, forecast, KPIs, energy + cost strip, context strip) · Simulation view (kitchen floor + hub tile) · right rail (decision feed + undo, escalation card in all states)
- [ ] Top bar: clock (shows `paused_reason`, `Day n of N`, phase), play/pause, speed, surge buttons
- [ ] Agent Network, Proof, chat drawer + proposal cards, warning banners (`sim_host_offline`, `hub_offline`, `live_transport_down`, `store_down`, `cap_unreachable`)
- [ ] `/sim` host panel: hub connection, last `tick_id`, "another sim host is running"

**D. Contract migration (from Kritazya, 2026-10-24) — your types in `src/types/contracts.ts` are on the older contract**
- [ ] ClockState / `live_clock` / ws `clock`: remove `slowed_reason`; `paused_reason` = null | manual | hub_waiting | sim_host_offline | run_complete (no `escalation` / `approval`); add `day_index`, `run_days`, `phase` (service | overnight | closed)
- [ ] Meter / `live_tick`: add `on_peak_month_peak_kw` (null if the tariff has no windowed charge) and `energy_kwh_month`
- [ ] TickState: add `warnings: Warning[]` (`{code, message, data}`; `cap_unreachable.data` has `target_kw` too)
- [ ] Escalation / `live_escalation`: statuses add `obsolete`; options carry `harm_score` + `rank`; add `updated_ts`, `block_start`, `default_option_id`, `active_option_id`, `deadline_sim_ts` columns; `projected.max_indoor_temp_change_c` may be `null` ("not modelled"); one escalation per block is updated in place (upsert by id)
- [ ] Decision `reason_code` adds `escalation_fallback`; `reduce` value is % of `rated_kw` (SIMULATION.md must cap draw at `value% × rated_kw`, G40)
- [ ] `delay` value 0 clears a hold; a hold ends by itself after `value` minutes (SIMULATION.md)
- [ ] Escalation card: fallback in force from the start, options by `rank`, states incl. *Deadline passed* and *Risk passed*; minimize mode draws `target_kw` as the target line; `cap_unreachable` banner text from its `data`; Undo only on reduce / delay items (UI.md)
- [ ] KitchenConfig: add `run_days`; Builder "Run for" control (UI.md)
- [ ] `sim_tick`: add `fast_forward`; honour `inputs.is_open: false` closed-hours behaviour (SIMULATION.md "Closed hours"); state carries across midnight and days
- [ ] Reconnect cue (your Q3): answer the replayed tick whose `tick_id` = `hub_welcome.tick_id`
- [ ] Live screen: `Day n of N`, phase chip, overnight overlay, end-of-day card + `Continue +1 day` (`next_day`) (UI.md)
- [ ] Re-run your mocks against the regenerated fixtures (`scenario/demo_cafe_multiday/` for the day change; the 120-tick evening stays)

## 5. Your fake data (all in `contracts/fixtures/`, read only)
| You need | Use this | How |
|---|---|---|
| FastAPI driving your simulation | `hub_protocol/server_to_hub.jsonl` (hub_welcome, sim_build, 120 × sim_tick) | `src/mocks/mockHubServer.ts` sends one line per tick at the chosen speed and waits for your `hub_report` |
| The expected shape of your hub's replies | `hub_protocol/hub_to_server.jsonl`, `hub_report.json`, `shapes/hub_report_*.json`, `shapes/command_ack_*.json` | Compare **shapes and invariants**, not values: your simulation's numbers will differ from the toy generator's, and that is fine |
| Every live screen (charts, KPIs, floor in viewer tabs, feed, escalations, clock, context) | `spacetime/rows_stream.jsonl` (one publish per tick) + `spacetime/tables/*.json` | Mock `useLive()` replays the stream; seed the other tables from `tables/` |
| REST (catalog, kitchen, commands, proposals, escalations, chat…) | `rest/*.json` (`{method, path, status, request, response}`, incl. 404/422) | Mock handlers match method + path |
| `/ws` (chat streaming, proposals, `LIVE_TRANSPORT=ws` fallback) | `ws/*.json`, `ws/stream.jsonl` | Replay in order |
| Builder inputs | `rest/get_catalog.json`, `shapes/kitchen_config.json`, `shapes/kitchen_config_minimize.json` | |
| Multi-day run (day close → overnight → next day → `run_complete`) | `scenario/demo_cafe_multiday/` (pending: next `fixture-builder` run; same stream files as the evening scenario; overnight as one row per 15-min block) | Mock clock walks the phases; Builder `run_days` |
| History behind the Proof screen and day-to-day inputs | `history/daily_inputs.json`, `rest/get_backtest.json` (pending: next `fixture-builder` run; fake June + July, label `simulated`) | Proof renders it, never as real savings |
| The scenario story (what happens when) | `scenario/demo_cafe/scenario.json`, `index.json`, `README.md` | Surge at tick 30, escalation `e_0001` opens at tick 50 with its fallback (dishwasher hold) applied in that step; Claude confirms the same option within authority; owner "start dishwasher" after tick 118 is rejected `job_running`. Multi-day: `scenario/demo_cafe_multiday/README.md` |

## 6. Two data paths in the UI (keep them separate)
- **Charts view → SpacetimeDB only** (engine numbers): `live_tick`, `tick_history`, `live_comparison`, `live_feed`,
  `live_escalation`, `live_clock`, `live_context`, `live_agent_log`.
- **Simulation view → `useDevices()` only**: in the `/sim` tab it returns the hub's current `Device[]` (appliance React
  state); in every other tab it returns `live_device` rows. Same Device shape, same components. No other screen imports
  `src/sim` or `src/hub`.

## 7. Big-picture docs (read, don't edit)
`docs/ARCHITECTURE.md` (parts, boundaries, flows) · `docs/CONTRACTS.md` §1 shapes, §2 REST + `/ws`, §5 SpacetimeDB tables,
§8 hub protocol, §9 appliance interface · `docs/design/SIMULATION.md` · `docs/design/UI.md` · `docs/PRINCIPLES.md` · `docs/DEMO.md`.
You do not need ENGINE, API, AGENTS, CONVEX or SPACETIMEDB internals; treat them as black boxes behind the fixtures.

## 8. Checks before you say "done"
`npm run build` and `npm test` (Vitest) pass · same seed + same `server_to_hub.jsonl` → byte-identical `hub_report`s across two
runs · `total_kw` = sum of devices · power never negative or above rated · every Command gets exactly one ack in its lane ·
lint forbids `Math.random` / `Date.now` in `src/sim`, `src/hub` · no screen imports `src/sim` / `src/hub` · every message type in
CONTRACTS.md renders against the mocks · labels on every data source ("simulated", "recorded", "measured (scaled)").

## 9. Out of scope — do not do these
Engine logic, forecasts or any cost math · FastAPI, Claude, Fetch agents, Convex, SpacetimeDB module code · changing a contract
shape or a fixture · real network calls to the backend (mocks only for now) · merging or rebasing with other branches ·
restructuring folders outside `frontend/`.

## 10. Session starter (paste into Claude Code)
```
ROLE = ashirwad. Read docs/team/ASHIRWAD.md first (it is my instruction set), then CLAUDE.md golden rules, and only the docs
it lists for today's task. Build only inside my scope, only against contracts/fixtures/. Do not merge, do not edit contracts,
fixtures, docs or other folders. Task: <task>. Restate it in ≤5 lines with the files you'll touch and the fixtures you'll use;
plan first if >50 lines. End with: what changed, tests run, stubs, contract questions.
```
