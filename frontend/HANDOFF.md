# Handoff prompt (paste into ChatGPT or a new Claude session)

You are taking over Ashirwad's work on **WattWise** (Cal Hacks 13.0, Oct 23–25 2026). Work carefully, keep the existing code style, and run `npx tsc -b` and `npm run build` (in `frontend/`) after every change.

## Project
WattWise keeps a restaurant's electricity peak (demand charges = highest 15-minute average kW of the month) under an owner-set cap. A simulated kitchen reports to one hub; the Python engine (Kritazya) decides and acts inside the owner's rules (importance: always_on / flexible / deferrable). When routine moves can't hold the cap, the engine raises an **escalation** with options; Claude picks one within the owner's **authority**, or hands it to the owner. Fetch.ai agents (Concierge + Weather / Grid / Events) post outside **context**. Two lanes run side by side: `without` vs `with` WattWise.

Read first: `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `docs/design/UI.md`, `docs/design/SIMULATION.md`, and **`docs/team/ASHIRWAD.md`** (my role and phases).

## My role (docs/team/ASHIRWAD.md)
- The whole `frontend/`.
- The simulation: `backend/engine/devices.py`, `hub.py`, `customers.py`, `fake_hub.py`, `backend/data/equipment_catalog.json`, `backend/tests/simulation/`.
- Azure Static Web Apps.
- Stay inside these folders. Kritazya owns the engine brain, backtest / proof data, SpacetimeDB and Container Apps (incl. `backend/engine/__init__.py`). Suyog owns the FastAPI API, the run loop, Claude, the Fetch agents, Convex and the ESP32.
- What the teammates need from my side is in **`frontend/FOR_TEAMMATES.md`**; keep it current too.

## Repo and branch
- `~/Downloads/WattWise` (github.com/EMP-Kritazya/WattWise).
- **All my work is on branch `ashirwad`. Never commit to main.** Each finished step is committed and pushed to `ashirwad`.
- Commits so far:
  - `a475af8` Simulation Phase 1
  - `1c9a9d6` Simulation Phase 2
  - `d1e5c15` Frontend data layer
  - `0d477ed` Step 4 UI
  - Step 5a Proof screen (latest commit on `ashirwad`)
- `backend/engine/__pycache__/` is untracked; leave it out of commits.

## Run
- Frontend (in `frontend/`, Node 24 via nvm):
  - `npm run dev:mock`: in-browser fake server, no backend. Open http://localhost:5173 and go Kitchen Builder → Build kitchen → Live → Play.
  - `npm run dev`: the real FastAPI on :8000 (Vite proxies `/api` and `/ws`).
- Live data source env vars:
  - `VITE_LIVE_TRANSPORT=spacetime`, `VITE_SPACETIME_URI`, `VITE_SPACETIME_DB`.
  - Without them the frontend uses `/ws`.
- Simulation tests (Python 3.11 venv; 23 pass):
  `cd backend && ~/.venvs/wattwise/bin/python -m pytest tests/simulation -q`

## Stack
- React 19, TS, Vite 7, Tailwind v4.
- shadcn/ui, hand-written in `src/components/ui`.
- Zustand, Recharts 3, react-router 7.
- three 0.186 with @react-three/fiber 9, drei 10 and postprocessing 3.

## Done

### Step 1–2: simulation (backend)
- **`equipment_catalog.json`:**
  - 11 types, each with `default_limits`.
  - The kW figures are **PLACEHOLDER**; their `source_note` says so.
  - HVAC is a thermal RC model.
  - The dishwasher must finish by 21:30, the ice machine by 21:00.
- **`devices.py` (SimDevice):**
  - Power models: fixed, cycling, thermal, demand_driven (order queue), job.
  - Commands:
    - `reduce` is clamped to `min_power_pct` and to the food-safety floor (refrigeration ≥ 50 %).
    - `delay` pauses a job.
    - Restoring pays back owed energy from an `owed_kwh` ledger.
  - A measured reading overrides one step.
  - Per-device seeded RNG.
- **`customers.py`:** seeded Poisson arrivals from a daily profile, plus surges.
- **`hub.py`:**
  - `report` / `deliver` / `devices` (the only door).
  - `advance(ts, minutes, orders, outdoor_temp_c)`.
  - `ingest_reading`.
- **`fake_hub.py`:** a deterministic hub for engine tests.
- **Sanity check:** about 22 kW mid-morning, 44 kW at the dinner peak and 6 kW overnight. A +40 lunch surge gives a 53 kW peak against a 40 kW cap.

### Step 3: frontend data layer
- **`src/types/contracts.ts`:** STUB copy of CONTRACTS.md. Replace it with `npm run gen:types` once the schema exists.
  - New types: LaneComparison, Escalation, Proposal, Context, AgentLog, ClaudeAuthority.
  - KitchenConfig gains `location`, `owner_preferences` and `authority`.
- **`src/transport/`:** one method per REST endpoint, plus `subscribe` for `/ws`.
  - Includes listEscalations / resolveEscalation, listProposals / confirmProposal, setAuthority, setPreferences, getContext and health.
- **`src/data/`:** all screens import from `@/data`, never from the store directly.
  - `index.ts` hooks: `useLive`, `useComparison`, `useLiveContext`, `useAgentLog`, `useEscalations` (newest first), `usePendingProposals`, `useLiveSource`, `startLive`, `requestSurge`.
  - `live.ts` switches between SpacetimeDB and `/ws`. If SpacetimeDB fails, it falls back to `/ws` and raises a `live_transport_down` warning.
  - `spacetime.ts` maps table rows to messages. **STUB:** `connectSpacetime` and `callRequestSurge` throw until Kritazya's generated bindings exist.
- **`src/store/sim.ts`:** comparison, escalations, proposals, context, agentLog (≤ 300 rows), and warnings keyed by code.
- **`src/mocks/server.ts`:**
  - Escalations every 30 sim minutes, starting at minute 20:
    - Odd ones: Claude resolves them after 2.5 s.
    - Even ones: they go to `awaiting_owner` and pause the clock (`paused_reason: "escalation"`).
  - A comparison after each tick.
  - Context and agent_log refresh hourly.
  - Chat replies "never touch…" and "cap N" become proposals.
- **Saved today and peak avoided** come from `LaneComparison`. The browser never subtracts the lanes.

### Step 4: UI (frontend)
- **Live page order:** WarningBanner → SimControls → **ContextStrip** → **EscalationCard** → 3D LiveFloor → KpiRow → device, trend and decision cards.
- **`components/live/EscalationCard.tsx`:** the latest escalation with its states:
  - "Claude is choosing…" (spinner)
  - "Claude chose" / "You chose"
  - "Waiting for you"
  - "Default applied"
  - The card also shows the chosen option's projected peak and cost, and Claude's rationale.
- **`components/live/ContextStrip.tsx`:**
  - Cells: outdoor temp with the next hours, price with a sparkline and grid stress, nearby event, crowd effect.
  - Each cell shows its live / recorded label and its source.
- **`components/live/EscalationDialog.tsx`:**
  - Shows each option with projected numbers, a within / outside authority badge and rule breaks.
  - **Mounted in `App.tsx`**, so it shows on every screen; a waiting escalation pauses the clock.
- **`pages/AgentNetworkPage.tsx` (`/agents`):**
  - An SVG graph: Concierge in the centre; Weather, Grid and Events around it; Claude, the engine and the owner below.
  - The last 6 agent_log rows animate as dots along their edges.
  - The last 50 messages are listed beside the graph.
  - Unknown agent ids still render.
- **`pages/BuilderPage.tsx`:**
  - Location preset (Marina, San Francisco: 37.80, −122.44).
  - Owner preferences textarea.
  - **Claude's authority:** enabled, max cap overrun in kW, extra delay minutes, extra reduce minutes, and may-go-below-min-power, with the note "refrigeration never below 50 %".
  - **Per-unit importance with inline limits:**
    - flexible: a min power % slider (floor 50 for refrigeration) and max minutes;
    - deferrable: max delay and finish-by.
  - The config sends per-type entries. Units that differ from their type default are applied after the build with `transport.setImportance(device_id, …)`.
- **`EquipmentType.default_limits`** is optional in the TS types. The mock catalog fills it, and mock `createKitchen` takes `config.authority`.
- **AssistantPanel:** a ProposalCard with Confirm / Cancel. After Confirm it re-reads the kitchen.

### Step 5a: Proof screen (frontend)
- **`pages/ProofPage.tsx`:** runs `runBacktest({ months: 12, assumptions_id: "base" })` on first visit, shows progress from `backtest_progress`, then loads `getBacktest` + `getProofExtras`. The last run is cached in the module while the app is open; "Re-run backtest" starts a new one.
  - Header badges: dataset label, tariff name, assumptions id, auditor status. **Numbers stay hidden unless `audit === "cleared"`** (DATA_AND_PROOF.md).
  - Year totals (Without / Timer / With, saved vs without, saved vs timer).
  - 12-month table: bill, peak kW and kWh per policy, both savings columns, January "partial (warm-up)", a checks icon with the details on hover.
  - Busiest day chart (Recharts) with both peaks marked.
  - Sensitivity table with the worst case highlighted.
- **`components/proof/ReplayMonth.tsx`:** plays the cached month hour by hour in 15 s with three running bills (Without / Timer / With) and a load chart revealed as it plays; pause / resume / replay; ends with that month's savings.
- **`ProofExtras` (types/contracts.ts) is PROPOSED, not in CONTRACTS.md.** It holds the tariff name, audit status, per-month savings, totals, busiest day, sensitivity and the replay series, so the browser never subtracts bills. Real endpoint (proposed): `GET /api/backtest/{run_id}/proof`.
- **`mocks/proof.ts`:** the mock backtest (moved out of `server.ts`) and `mockProofExtras`. The replay's last hour equals the table's bill for that month.

### Earlier: 3D live floor (`src/components/live/floor/`)
- Isometric R3F scene with Restaurant, Device3D, Ambient, Scenery, Furniture, Effects3D, Hud and OperationsPanel ("What is running?").
- Equipment focus mode is on by default.
- Running devices get a status pad, tint and tag.
- Camera views: Isometric, Top-down, Street, POV.
- A labels toggle, Follow, side by side, and demo mode.
- Demo keys: Space play/pause · C +40 customers · S side by side · V cycle views · L labels · F follow · Esc exit.

## Next: rest of Step 5 (Phase 4–5 in ASHIRWAD.md)
1. **Badges:** make the mock report one device as `source: "measured"` and the hub report as `mixed`; show "measured (scaled)" on that device in the 3D floor, DevicePowerCard and the "What is running?" panel, and a hardware badge in the StatusBar (from `/api/health` `hardware`).
2. **Demo preset in the mock:** DEMO.md says Friday **17:30** (mock starts 11:30), 120×, Giants game 19:05 in recorded context, one escalation ~2 min in. Add a demo-mode Builder preset ("Demo Café", Marina SF).
3. **Azure Static Web Apps:**
   - `staticwebapp.config.json` with an SPA fallback to `index.html`, so `/agents` and `/proof` work on refresh;
   - a GitHub Actions workflow that builds `frontend/` and deploys `dist`;
   - deploy the mock build first (`VITE_MOCK=1`) so there is a working link, then switch the env to the real API / SpacetimeDB URLs.
4. **Join up once teammates deliver** (see `FOR_TEAMMATES.md`): real API, SpacetimeDB bindings, real backtest, then 5 clean demo runs and the 3–5 min video.
5. **Later:**
   - Replace the PLACEHOLDER kW figures with FSTC / ENERGY STAR values.
   - Plug in the SpacetimeDB bindings in `src/data/spacetime.ts`.
   - Switch to generated types (`npm run gen:types`).
   - Code-split the three.js bundle; the build warns about chunks over 500 kB.

## Rules (CLAUDE.md / UI.md)
- **No numbers in the UI** except formatting. Every figure comes from the engine, including saved today, peak avoided and projected values. Visual-only ratios (glow, bar width) are fine.
- **Labels:** everything simulated says "simulated". kW has 1 decimal, $ has 2.
- **Colors:**
  - always_on grey, flexible blue, deferrable amber;
  - Without lane red, With lane green.
- **Engine rules:**
  - no I/O in `engine/`;
  - deterministic seeds;
  - units in names;
  - the hub is the only door;
  - food-safety floor: refrigeration ≥ 50 %.
- **Contracts:** never hand-write contract shapes as final, and don't change `docs/CONTRACTS.md` without the team.

## Open questions and gaps (raise with the team)
- Who calls `hub.advance` each tick? Probably Suyog's run loop (ARCHITECTURE.md: runtime = Suyog).
- **SpacetimeDB:** the generated bindings, and the `request_surge` reducer signature.
- **Proof data:** the PROPOSED `ProofExtras` / `GET /api/backtest/{run_id}/proof` needs Kritazya's agreement (or another shape), plus a cached-run lookup for demo mode.
- **Endpoints:** no tariff list endpoint.
- **Messages:** no state replay on `/ws` connect, and no "warning cleared" message.
- **Importance:** it is per equipment type in KitchenConfig. Per-unit overrides go through `PUT /api/kitchen/devices/{id}/importance`.

## Gotchas
- **`scrollIntoView`:** in Chromium it returns a Promise. Never return it from a `useEffect`.
- **z-index:**
  - drei `<Html>` labels use z-index up to 60;
  - the floor legend is at `z-[45]`;
  - the HUD is at `z-[80]`.
- **Lights:** mounting or unmounting three.js lights recompiles shaders. Keep lights mounted and change their intensity instead.
- **Shaders:** custom shaders that can emit NaN black out the frame through Bloom. N8AO and SoftShadows also blanked it. Use standard materials.
- **Stale HMR:** it can make the floor look wrong. Hard-reload (e.g. add `?fresh=1` to the URL).
- **Replay animation:** a requestAnimationFrame timestamp can be earlier than the `performance.now()` taken at start; clamp progress at 0 or `steps[-1]` crashes the page.
- **Edit-tool failures:** after shell / sed edits, re-read a file before using the Edit tool on it.
