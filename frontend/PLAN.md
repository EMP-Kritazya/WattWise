# PLAN.md — Ashirwad's build plan (Frontend: UI + Simulation + Hub)

Source of truth: `docs/team/ASHIRWAD.md` on `main` (commit `0dc6a34`), plus `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/PRINCIPLES.md`,
`docs/CONTRACTS.md` (§1, §2, §5, §8, §9), `docs/design/SIMULATION.md`, `docs/design/UI.md`, `docs/DEMO.md`, `Main_Gaps.md` and
`contracts/fixtures/README.md`. When this plan and those files disagree, **they win**. Every item below maps to a line in
ASHIRWAD.md §4 (what to build) or §8 (checks).

Status key: ☐ to do · ◐ partly there (existing code to rework) · ☑ done and tested.

---

## 0. Ground rules (ASHIRWAD.md §2, §3, §9)

**I may create and edit only:**
- `frontend/` (everything: `src/sim/`, `src/hub/`, `src/screens/`, `src/data/`, `src/mocks/`, configs, tests);
- `backend/data/equipment_catalog.json`;
- `infra/` Static Web Apps files.

**I never edit:**
- `docs/`, `CLAUDE.md`, `README.md`, `Main_Gaps.md`;
- `contracts/`, including the fixtures;
- anything else in `backend/`, plus `agents/`, `spacetime/`, `convex/`, `firmware/`, `.github/`.

**How I work:**
- **Build only against `contracts/fixtures/`:** no calls to Suyog's API or Kritazya's SpacetimeDB while developing; mocks only.
- **No merges:** no merging, no PRs to `main`, and no pulling teammates' branches into mine. Commit to `ashirwad` only.
- **Shape problems:** if a shape looks wrong, keep the code matching the contract as written and add the problem to §7, "Contract questions".
- **Fixtures are read-only.**
- **No arithmetic in screens:** screens compute nothing. The simulation computes only physical power and state; the hub only sums `total_kw` and computes `power_pct`.
- **Determinism:** no `Math.random()` or `Date.now()` in `src/sim/` or `src/hub/`. One seeded PRNG per kitchen, seeded from `sim_build.seed`.

---

## 1. Decisions needed before coding

**D1. Bring the new base into `ashirwad`.** ☑ Done: rebased onto `main` `0dc6a34`. `ashirwad` sits on `cb0d598`, but `contracts/fixtures/` and the new docs only exist on `main` (`0dc6a34`).
- **Recommendation:** rebase `ashirwad` onto `origin/main`.
  - `main` is the shared base the task file says to branch from, not a teammate's branch.
  - The rebase is conflict-free: `0dc6a34` touches no file under `frontend/` or `backend/`.
  - Then force-push `ashirwad`.
  - (`architecture-separation`, which ASHIRWAD.md names, doesn't exist on GitHub; its content appears to be `0dc6a34`.)
- **Alternative:** stay on the old base and read the fixtures from a local, gitignored copy taken with `git show`.

**D2. Remove my old Python simulation from the branch.** ☑ Done. These files are now outside my scope, and on merge they would add files to Kritazya's `backend/engine/`:
- `backend/engine/devices.py`, `hub.py`, `customers.py`, `fake_hub.py`;
- `backend/tests/simulation/`.

  Deleting my own additions restores his folder to exactly what `main` has; the physics moves to TypeScript (§3 B).
  **Recommendation:** delete them in one commit.

**D3. What the Simulation view draws.**
- UI.md specifies **one tile per device**, with a thin line to a **Hub tile** that pulses each tick, plus physical gauges.
- **Recommendation:** build the tile floor exactly as specified.
- The existing 3D floor is not in the spec. Either keep it as an optional "3D" look inside the Simulation view (reading only `useDevices()`), or retire it.
- Your call; it's extra scope either way.

---

## 2. Target layout of `frontend/src/` (CLAUDE.md "Repo layout", ARCHITECTURE.md)

```
src/
  types/        contracts.ts — hand types for every shape I use, each marked // STUB: replace with generated types
  sim/          appliances/ (fixed, cycling, thermal, demand_driven, job) · customers.ts · kitchen.ts · rng.ts · store.ts
                __tests__/  (Vitest)
  hub/          hub.ts (apply → step → HubReport per lane) · link.ts (/ws/hub protocol client) · hubStore.ts
  data/         useLive() (SpacetimeDB tables; /ws fallback) · useDevices() · useApi() (REST) · transport switch
  mocks/        index.ts (VITE_MOCKS=1 switch) · fixtures.ts (loads contracts/fixtures read-only) · rest.ts · liveRows.ts
                · viewerWs.ts · mockHubServer.ts · spacetimeReducers.ts
  screens/      Builder · Live (Charts | Simulation) · AgentNetwork · Proof · SimHost (/sim)
  components/   shared UI pieces (chat drawer, proposal card, escalation card, feed, charts, floor tiles, ui/)
```

**Boundaries, enforced by ESLint:**
- `screens/` and `components/` never import `src/sim` or `src/hub`.
- `src/sim` never imports screens or data hooks.
- No backend imports anywhere.
- The **only** bridge is `src/data/useDevices()`.

**Reading fixtures without copying them:**
- A Vite alias `@fixtures` points to `../contracts/fixtures`, with `server.fs.allow` set to the repo root.
- JSON is imported directly; `.jsonl` is loaded with `?raw` and split by line.
- Fixtures are read-only and never copied into `frontend/`.

---

## 3. Build plan (ASHIRWAD.md §4, in its order)

### A. Skeleton

**A1. App and routes.** ◐ The Vite, React, TS, Tailwind, shadcn/ui and Recharts app already exists.
- Routes: Builder, Live, Agent Network, Proof, and a new **`/sim`**.
- Rename `pages/` → `screens/`.
- Add **Vitest** (`npm test`) and **ESLint** (flat config) as dev dependencies inside `frontend/`.

**A2. Types.** ☑ Contract-aligned hand types are in place; `ProofExtras` and its endpoint are removed. Every generated boundary remains marked `// STUB`.
- **Changed shapes:**
  - EquipmentType: drop `min_power_pct`; add fixed `params` keys per power model and `default_limits`.
  - KitchenConfig: add `peak_mode` (`minimize | cap`, with `peak_cap_kw` null for minimize).
  - Device: add `power_pct` and `physical`.
  - HubReport: add `hub_id`, `lane`, `tick_id` and `acks`.
  - Decision status: only `executed | undone`.
  - Proposal kinds: all six.
  - ClockState: add `tick_id` and `slowed_reason`.
  - `GET /api/kitchen`: returns `{config, devices, tariff}`.
  - Health: add `sim_host`.
  - Warnings: add `sim_host_offline`, and `data` per code.
- **New shapes:**
  - Tariff, Command (with `lane`), CommandAck.
  - Meter: add `target_kw` and `price_usd_per_kwh_now`.
  - Every SpacetimeDB row type (§5).
  - Every hub protocol message (§8).
- **Remove** `ProofExtras` and its endpoint: it isn't in the contract (golden rule: never invent a shape). Proof's gaps go to §7.

**A3. Mocks** (`src/mocks/`, switched by `VITE_MOCKS=1`). ☑ Fixture REST, live rows, viewer `/ws`, reducers and hub server are implemented from the read-only shared fixtures:
- **REST** (`rest.ts`): match method and path against `rest/*.json` and return `response` with its `status`.
  - Includes the `_404` and `_422` examples, served when the request matches theirs.
  - Errors come back as `{detail}`.
- **SpacetimeDB rows** (`liveRows.ts`):
  - Seed every table from `spacetime/tables/*.json`.
  - Replay `spacetime/rows_stream.jsonl`, one publish per tick at the clock speed, into `live_tick`, `tick_history`, `live_device` and `live_comparison`.
  - Feed, escalation, clock, context and agent-log rows advance in step with the tick, taken from `ws/stream.jsonl` and converted to row form, so the screens move through the scenario: surge at tick 31, escalation at tick 60, choice at tick 62.
- **Viewer `/ws`** (`viewerWs.ts`): replays `ws/stream.jsonl` in order. It feeds chat streaming and proposals, and drives everything when `VITE_LIVE_TRANSPORT=ws`.
- **Reducers** (`spacetimeReducers.ts`): `request_surge(customers, duration_min)` validates 1–80 customers and 15–120 min, then records the request, as in `spacetime/reducers/request_surge.json`.
- **Hub server** (`mockHubServer.ts`):
  - Plays `hub_protocol/server_to_hub.jsonl`: `hub_welcome`, `sim_build`, then 120 `sim_tick`s.
  - Sends one tick per interval at the chosen speed and **waits for the matching `hub_report`** before sending the next.
  - Also offers `hub_welcome_host_taken.json` for testing the refusal.

**A4. Data hooks** (`src/data/`). ☑ Typed live rows, the `/sim`-aware device bridge and the REST facade are implemented and were verified through a temporary all-table debug route (removed after verification).
- **`useLive()`:** typed rows for each SpacetimeDB table. It uses SpacetimeDB by default (generated bindings later), falls back to `/ws` (messages converted to the same row shapes), or uses the mock rows. One switch, invisible to screens.
- **`useDevices()`:** in the `/sim` tab, the hub's current `Device[]` per lane; in every other tab, `live_device` rows (parsing `physical_json`). Same Device shape either way.
- **`useApi()`:** one function per REST endpoint in CONTRACTS.md §2, used by the Builder, clicks, undo, escalation choices, proposals and chat.

### B. Simulation and hub (`src/sim/`, `src/hub/`; design in SIMULATION.md, CONTRACTS.md §8 and §9)

**B1. Equipment catalog** (`backend/data/equipment_catalog.json`). ◐ Bring it to the contract:
- The `params` keys per model:

  | Model | Keys |
  |---|---|
  | fixed | `{}` |
  | cycling | `{duty_idle_pct, duty_busy_pct}` |
  | thermal | `{setpoint_c}` |
  | demand_driven | `{idle_kw, kw_per_order}` |
  | job | `{cycle_min}` |

- `default_limits` on every type: dishwasher `must_finish_by: "15:30"`, ice machine `"22:00"`, walk-in cooler `min_power_pct: 50`, HVAC 40.
- No top-level `min_power_pct`.
- Replace the PLACEHOLDER power figures with FSTC / ENERGY STAR values, each with its `source_note`.
- **Values may differ from the fixture catalog; shapes may not.**

**B2. Appliance interface** (CONTRACTS.md §9): `step(minutes, inputs)`, `reading(): Device`, `apply(command): CommandAck`. Power models per SIMULATION.md:

| Model | Behaviour |
|---|---|
| fixed | `rated_kw` while on, 0 while off; lights on during opening hours |
| cycling | duty cycle between `duty_idle_pct` and `duty_busy_pct`, rising with how busy the kitchen is; `physical.box_temp_c` |
| thermal | **one dining-room temperature per kitchen, shared by every HVAC unit** (Main_Gaps G23); RC model; outdoor temperature from `inputs.outdoor_temp_c`, else a built-in summer-day curve; `physical.indoor_temp_c` |
| demand_driven | `idle_kw + kw_per_order × orders_in_progress`, capped at `rated_kw`; `physical.orders_in_progress` |
| job | `rated_kw` for `cycle_min` when triggered (dishwasher: dirty racks ≥ N; ice machine: ice level low); `physical.dirty_racks` / `ice_level_pct` / `job_remaining_min` |

Always 0 ≤ `power_kw` ≤ `rated_kw`.

**B3. Commands** (CONTRACTS.md Command and CommandAck, Main_Gaps G20 and G21):
- `reduce` (value = power %) and `restore`; the appliance catches up after `restore`.
- `delay` (value = minutes from when the hub applies it): on an idle job it holds the next job (`waiting`); on a waiting job it replaces the hold. A **running** job → `ok: false, reason: job_running`.
- `start`, `on`, `off`: `off` on an already-off unit → `ok: false, reason: already_off`.
- **Clamping:** a value outside the physical limits is applied clamped → `ok: true, applied_value ≠ value, reason: out_of_range`. Each appliance has its own physical floor; the fixtures' 20 % is fixture-only (GAPS.md).
- An unknown device → `ok: false, reason: unknown_device`.
- Idle job devices report `state: "off"`.
- The simulation enforces **physics only**; the owner's rules are the engine's job.

**B4. React state per lane.**
- One store per lane (`without`, `with`), using Zustand vanilla stores so the same code runs in Vitest and in React.
- Applying a Command updates the appliance's state, which re-renders it.
- Physics is plain TypeScript (pure functions over the state); the store holds the result.

**B5. Customers** (`customers.ts`).
- Seeded Poisson arrivals from a weekday hourly profile: lunch about 12:00–13:30, dinner about 18:30–20:30. Labelled "simulated customer flow".
- Multiplied by `inputs.crowd_multiplier`.
- **Surges:** each arrives once, in its `sim_tick`, and stays active for `duration_min` (G27).
- **One stream for both lanes.** Customers become orders (cooking load) and dirty racks (dishwasher trigger).

**B6. Hub** (`hub.ts`). Each tick:
1. Apply the tick's `commands`, each to its `lane`, collecting one ack per Command.
2. Step both kitchens `minutes` from `sim_ts`, with the same customers and surges.
3. Build one HubReport per lane:
   - `hub_id: "sim_hub"`, `lane`, `tick_id`;
   - `ts = sim_ts + minutes`;
   - every `reading()`;
   - `total_kw` = the exact sum of device `power_kw`, rounded once to a fixed precision, so equality holds;
   - `power_pct = round(100 × power_kw / rated_kw)`;
   - `customers_per_hour`, that lane's `acks`, and `source: "simulated"`.

**B7. Hub link** (`link.ts`, CONTRACTS.md §8).
- **Outgoing:** sends `hub_hello` `{protocol: 1, hub_id: "sim_hub", role: "sim_host", client: "wattwise-web/0.1"}`.
- **`hub_welcome`:** if `accepted: false, reason: "host_taken"`, stop simulating and show "another sim host is running".
- **`sim_build`:** build both kitchens from `config`, `catalog` and `devices` (the roster: off, 0 kW, no `physical`), seeded from `seed`, starting at `start_sim_ts`.
- **`sim_tick`:** apply, step, then reply `hub_report` with the same `tick_id`.
- **`replay: true`:** step without replying, except for the last replayed tick (see contract question Q3).
- **`sim_control`:** reflect play/pause/speed in the host panel; the hub never steps on its own.
- The URL comes from `VITE_HUB_WS_URL` (default `/ws/hub`). The mock server plugs in at the same interface.

### C. Screens (UI.md)

**C1. Kitchen Builder.** ◐
- **Equipment:** counts 0–5 from `GET /api/catalog`.
- **Each unit:** importance with its limits inline (exists; needs the new `default_limits`).
- **New "Peak goal":** `Minimize peak | Hard limit`, with kW only for Hard limit, and the helper line: "Your highest 15-minute average power. Demand charges are based on this."
- **Settings:** location, preferences, operating hours, tariff preset (`demo_tariff_v1`, read-only for now), and seed (hidden in demo mode).
- **Claude's authority,** with the food-safety note.
- **Build kitchen:** `POST /api/kitchen`, then a short building state (the "21 days" warm-up text goes, since warm-up is TBD), then Live.

**C2. Live screen.**
- **Layout:** top bar · centred **`Charts | Simulation`** toggle (per viewer, remembered in localStorage; both views stay subscribed) · the selected view · right rail · chat drawer.
- **Charts view (SpacetimeDB only):**
  - two-lane chart from `tick_history` (last 3 sim hours) with the peak cap line, the month peak line and the dashed forecast on the `with` lane from `live_tick.forecast_kw_json`;
  - KPI row from `live_tick` and `live_comparison`;
  - energy and cost strip from `live_tick`: energy today, price now, cost today and month, per lane;
  - context strip from `live_context`.
- **Simulation view (`useDevices()` only):**
  - a tile per device: icon, name, kW, % of rated, state, importance badge, physical gauge;
  - a Hub tile with total kW, pulsing each tick, with lines to every tile;
  - clicking a tile opens a menu: on/off, start job, change importance (REST);
  - with `HARDWARE=esp32`, a "hardware" badge and hub online/offline; "measured (scaled)" on measured devices.
- **Right rail:**
  - decision feed, newest first: time, device, action, explanation, effect, Undo, and an "AI" tag;
  - escalation card in every state, with the option buttons **inside the card** for "Waiting for you" (UI.md). The current modal dialog is replaced.

**C3. Top bar.**
- Clock and day, showing `paused_reason` (escalation, approval, hub_waiting, sim_host_offline) and `slowed_reason`.
- Play/pause and speed (1×, 30×, 120×, 600×).
- `+20` / `+40` customers: the `request_surge` reducer, or `POST /api/events/customers` when `LIVE_TRANSPORT=ws`.
- Customers per hour now.

**C4. Other screens.** ◐
- **Agent Network:** from `live_agent_log`. Nodes use the contract's agent names: concierge, weather, grid, events, claude, engine.
- **Proof:** only what `BacktestResult` carries; see Q1.
- **Chat drawer:** streaming, with proposal cards for **all six kinds** and Confirm / Cancel.
- **Warning banners:** `sim_host_offline`, `hub_offline`, `live_transport_down`, `store_down`, `cap_unreachable`, using `data` for the message.

**C5. `/sim` host panel.** Hub connection state, last `tick_id`, ticks behind, and "another sim host is running" when refused.

### D. Static Web Apps (`infra/` + `frontend/public/`)
- **`staticwebapp.config.json`:** SPA fallback, so `/sim`, `/agents` and `/proof` survive a refresh.
- **Build-time env:** `VITE_API_URL`, `VITE_HUB_WS_URL`, `VITE_LIVE_TRANSPORT`, `VITE_SPACETIME_URI`, `VITE_SPACETIME_DB`, `VITE_CONVEX_URL`.
- **Deploy:** with the SWA CLI and a deployment token. A GitHub workflow would live in `.github/`, outside my scope, so I'd ask first.

---

## 4. Tests and checks (ASHIRWAD.md §8, SIMULATION.md "Tests")

**Vitest:**
- **Determinism:** the same seed and the same `server_to_hub.jsonl` give **byte-identical `hub_report`s** across two runs.
- **Hub totals:** `total_kw` = the sum of devices, on every report.
- **Power range:** power is never negative or above rated.
- **Acks:** every Command gets **exactly one** ack, in its lane.
- **Reduce:** a reduce to 40 % gives 40 % of the normal draw for that minute.
- **Delay:** a delayed job starts no earlier than its delay. A running job rejects a delay with `job_running`.
- **Shapes:** reports from the fixture tick stream pass shape checks against `hub_to_server.jsonl` and `shapes/hub_report_*.json` (shapes and invariants, not values).
- **Mock REST:** returns each fixture's `status` and `response` for its method and path.

**ESLint:**
- `Math.random` and `Date.now` are banned in `src/sim` and `src/hub`.
- Screens and components may not import `src/sim` or `src/hub`.

**Manual:**
- **Message coverage:** every message type in CONTRACTS.md renders against the mocks.
- **Labels:** "simulated", "recorded", "measured (scaled)", "illustrative" (tariff) and "fake fixture data" on Proof.
- **End to end:** Builder → Live works end to end over both mock SpacetimeDB rows and the `/ws` fallback.

**Gate:** `npm run build` and `npm test` pass before any commit is called done.

---

## 5. Order of work (one module per session; small commits)
1. D1, D2 and D3 decided. Base updated; old Python simulation removed.
2. A2 types, then A3 mocks, then A4 hooks, verified with a debug page that dumps every table and message.
3. B1 catalog, then B2–B5 simulation, then B6 hub, then the Vitest suite green.
4. B7 link with `mockHubServer`, then the `/sim` panel (C5). Determinism test on the full 120-tick stream.
5. C2 and C3 Live (Charts first, then Simulation), then the right rail and escalation card.
6. C1 Builder, then C4 (Agent Network, Proof, chat, banners).
7. ESLint rules, the §4 checklist, then D (Static Web Apps).
8. Session summary each time: what changed, tests run, stubs, contract questions (ASHIRWAD.md §10).

## 6. What carries over from the current branch
- **Keep and adapt:**
  - the app shell, routing, theme, `lib/format.ts` and the shadcn `ui/` components;
  - chat drawer and proposal card;
  - decision feed, KPI row, chart, context strip and warning banner (rewired to SpacetimeDB rows);
  - Agent Network graph (node names fixed) and Builder sections;
  - the Proof layout (trimmed to `BacktestResult`).
- **Replace:**
  - `mocks/server.ts`, `mocks/catalog.ts` and `mocks/proof.ts` → fixture-driven mocks;
  - `transport/` → `data/useApi()`;
  - `store/sim.ts` → `useLive()` row store;
  - `EscalationDialog` → buttons inside the card.
- **Remove:** `ProofExtras` (not in the contract); the old Python simulation (D2).
- **Decide (D3):** the 3D floor.

## 7. Contract questions for Kritazya (kept as written until answered)
- **Q1, Proof data:** `BacktestResult` has no savings columns, busiest-day series, sensitivity rows or replay series, yet UI.md asks for all four, and the browser may not compute them. What shape will carry them?
- **Q2, Context strip:** UI.md wants "next hours" and a price sparkline, but `live_context` holds only summary strings. May the strip read `GET /api/context` (full Context) over REST, or will `live_context` gain hourly columns?
- **Q3, Reconnect replay:** the hub "answers only the last replayed tick", but it can't know which replayed tick is last. Is the first non-replay `sim_tick` the cue? Or should the hub reply to the last tick with `replay: true` when the server sends a marker?
- **Q4, Tariff list:** there's no tariff list endpoint, so the Builder's "tariff (preset)" is fixed to `demo_tariff_v1` for now.
- **Q5, Agent Network:** the contract's agent names don't include `owner`, yet UI.md's graph has Claude and the engine "as nodes". Should owner messages (escalation answers) appear on the graph at all?
- **Q6, Missing docs:** CLAUDE.md still points to `docs/TIMELINE.md` and `docs/DECISIONS.md`, which were removed. Where do gates and merge order live now?
- **Q7, Branch name:** ASHIRWAD.md says to branch from `architecture-separation`, which doesn't exist on GitHub. Is `main` at `0dc6a34` the intended base?

## 8. Merging with Suyog later (not now)
Nothing is merged in this phase. When Suyog's backend is ready and the team decides to integrate:
- **The seam is the hub protocol** (CONTRACTS.md §8): my `src/hub/link.ts` ↔ his `runtime/hub_link.py`. Both are built against the same `hub_protocol/` fixtures, so they should agree byte for byte.
- **First integration run:**
  - his API with `KITCHEN_IMPL=fake`;
  - my `/sim` tab pointed at his `/ws/hub`;
  - my viewer tabs with `VITE_LIVE_TRANSPORT=ws` until SpacetimeDB bindings exist.
- **REST and `/ws`:** `useApi()` and the `/ws` fallback against his endpoints, compared with the `rest/` and `ws/` fixtures.
- **Branch hygiene:** my branch touches only `frontend/`, `backend/data/equipment_catalog.json` and `infra/` Static Web Apps files, so merging with `suyog` should have no file overlap.
