# Handoff prompt (paste into ChatGPT or a new Claude session)

You are taking over Ashirwad's work on **WattWise** (Cal Hacks 13.0, Oct 23–25 2026). Work carefully, keep the existing code style,
and run `npm run build` and `npm test` (in `frontend/`) before calling anything done.

## ⭐ CURRENT TASK (Oct 24, latest): build the Toy Box restaurant design
**Spec:** `frontend/UI_CONCEPTS.md`, chosen by Ashirwad. **Visual target:** `frontend/design/toybox-restaurant-mockup.html`; open it in a browser.

The whole restaurant in the current `plan.ts` layout, restyled as a toy miniature with ink outlines, plus a right column:
- a 15-min peak gauge (With needle, plus a ghost needle for Without);
- the **demand-charge card** (Without +$67.20 / With $0 extra);
- a Claude card.

### Build order (UI_CONCEPTS.md §5)
1. **Step 1, done and pushed (commit `6ac918d`):** toon materials, ink outlines, Toy Box palette, warm lighting, raised Street view.
   - `src/components/live/floor/toon.tsx`:
     - `<Toon>` is a drop-in for `meshStandardMaterial`. It uses a 3-step gradient and ignores metalness / roughness.
     - `<Ink>` is drei `Outlines`, with **thickness in screen pixels** (default 2.2). The drei default branch is pixel-based.
     - `floorPattern()` draws checker or plank textures.
   - `palette.ts`: `BACKGROUND #FFF6E9`, `INK #22223B`, `FLOOR` per room as `[pattern, a, b]`, `WALL`, `INNER_WALL`, `WINDOW`, `APPLIANCE` (one pastel per type), `APPLIANCE_BY_CATEGORY`, `OFF_TINT`.
   - `Scenery`, `Device3D`, `Ambient` (hub, lamps), `Furniture`: all use `<Toon>`; walls, appliances and props have `<Ink>`.
   - `LiveFloor`:
     - warm ambient, hemisphere and key light;
     - `Environment` removed (toon ignores it);
     - `ToneMappingMode.NEUTRAL`;
     - Street pose `pos [10.5,10,21] → target [10,0.4,4.5]`, looking down over the dining room as Ashirwad asked.
2. **Step 2, done by Codex (commit `57609e6`):** recognisable appliance shapes and the four states, on the appliance itself (UI_CONCEPTS.md §2):
   - **Running:** pastel, red LED, working detail lit.
   - **Reduced:** teal `#2EC4B6` floor ring, outline and LED; the cable to the hub turns teal and dashed.
   - **Held:** faded toward grey, dashed amber `#FFB703` ring, white clock badge.
   - **Off:** grey `#D9D4CC`.

   Implemented in `Device3D.tsx`, `Restaurant.tsx` and `palette.ts`: running red LED; reduced teal outline/ring/LED and dashed
   teal cable; held faded body, dashed amber ring and 3D clock badge; off neutral grey. Added fryer baskets, four grill burners,
   oven/dishwasher handles, reach-in doors and ice-bin details.
3. **Step 3, done by Codex (commit `56c1409`):** toy diners (block body and round head), a guest queue at the door after +40, warm table glows and toy-colour furniture.
   - `Ambient.tsx` now supplies deterministic toy diners, a six-person entrance queue and table `LightPool`s.
   - `Restaurant.tsx` derives visual seat occupancy from contract `customers_per_hour`; an unconsumed `surge_request` of +40 makes the queue appear immediately, even while paused. No derived business number is displayed.
   - Furniture, diners and table glows remain hidden when **Equipment focus** is on; the table pools follow the lights device reading.
   - Browser-verified at `/live` in demo mode after pressing **+40 customers** while the fixture was paused.
4. **Step 4, done by Codex (commit `594d8db`):** the full-screen demo right column uses Fredoka and Nunito; white cards have ink outlines and 22 px corners.
   - **Gauge:** `live_tick.block_avg_kw` per lane against `target_kw`.
   - **Demand-charge card:** the escalation's `accept_overrun.projected.cost_delta_usd` (67.20 in the fixtures) against the chosen option's `cost_delta_usd` (0).
   - **Claude card:** from `live_escalation`.
   - **Also:** the demo hides the appliance/debug sidebar and duplicate KPI strip. Outside demo mode, the existing keyboard-accessible appliance inspector and owner controls remain available.
   - `ToyBoxRail.tsx` reads typed `live_tick` and `live_escalation` rows directly. Gauge geometry is presentational only; every displayed kW and dollar value remains contract-provided.
   - Browser-verified at `/live` in full-screen demo mode: 37.9 kW With, 33.2 kW ghost Without, 40.0 kW cap, +$67.20 projected overrun, $0 chosen-option cost and “Claude chose 3 of 3.”
5. **Step 5, done by Codex (commit `594d8db`):** when a new executed `live_feed` decision arrives, unrelated appliances fade 30% toward the Toy Box background, their secondary status effects and cables quiet down, and the changed appliance receives a brighter outline, cable and light.
   - The pinned museum card stays for 6.5 seconds and uses only the engine decision: appliance/action plus `effect.peak_before_kw` → `effect.peak_after_kw`.
   - It reuses each appliance's always-mounted drei `Html` anchor instead of adding another floating React root.
   - Browser-verified during a 600× fixture replay: the walk-in cooler decision pinned to the appliance as “Turn down to 50% · 15-min peak 40.1 kW → 39.2 kW.”

### Rules
- **No numbers from the browser:** never compute a number, e.g. kW × $/kW. If a figure isn't in the contract, show kW only and add a contract question.
- **3D floor features:** keep them all. Camera views, demo mode and side by side stay; only the look changes.
- **Checks:** run `npm run build` and `npm test`, then check in the browser with `npm run dev:mocks` (port 5174).

### Uncommitted work in the tree (yours, ChatGPT's earlier session)
- **The fixture pause/play/reset fix:** `src/mocks/liveRows.ts`, `rest.ts`, `viewerWs.ts`, plus `src/mocks/fixtureControl.test.ts`.
- **Claude's added fix inside it:** in both `viewerWs.ts` and `liveRows.ts`, pressing Play after the 120-tick scenario ends now restarts it, where before it paused again at once. Keep that when you finish.
- **Commit it** once it's verified, then commit this file.

### Known issue
- **Console warnings:** React logs many "synchronously unmount a root while React was already rendering" warnings from drei `<Html>` labels on the floor.
- **Fix later:** keep the labels mounted and toggle their visibility instead.

## Read first, in this order
1. **`docs/team/ASHIRWAD.md` on `main` (commit `0dc6a34`).** It is Ashirwad's instruction set; it wins over every other doc about what he builds or may touch.
2. **`CLAUDE.md` golden rules**, especially:
   - 1: the engine computes every number;
   - 13: the hub is the only door;
   - 14: FastAPI owns time; no wall clock or unseeded randomness in `src/sim` / `src/hub`.
3. **The rest:**
   - `docs/ARCHITECTURE.md`, `docs/PRINCIPLES.md`;
   - `docs/CONTRACTS.md` §1, §2, §5, §8, §9;
   - `docs/design/SIMULATION.md`, `docs/design/UI.md`, `docs/DEMO.md`;
   - `Main_Gaps.md`, `contracts/fixtures/README.md`.
4. **`frontend/PLAN.md`:** the step-by-step plan that maps every ASHIRWAD.md task to files and tests. Follow it in order.

## The project in 5 lines
WattWise keeps a restaurant's 15-minute electricity peak under the owner's cap.
- **Simulation and hub:** a **browser simulation** (Ashirwad: `frontend/src/sim/`) models appliances and customers in one sim host tab (`/sim`). A **hub** (`frontend/src/hub/`) talks to FastAPI over `/ws/hub`.
- **Clock and engine:** FastAPI (Suyog) sends a `sim_tick` each simulated minute. The hub applies Commands, steps the simulation and replies with `hub_report`. The engine (Kritazya) computes every number and decides every 5 ticks.
- **Escalations:** Claude picks among engine options inside the owner's authority.
- **Screens:** they read engine numbers only from SpacetimeDB (or the `/ws` fallback). Appliances are drawn only through `useDevices()`.

## Scope (ASHIRWAD.md §2, strict)
- **May edit:** `frontend/`, `backend/data/equipment_catalog.json`, and the `infra/` Static Web Apps files.
- **Never edit:**
  - `docs/`, `CLAUDE.md`, `README.md`, `Main_Gaps.md`;
  - `contracts/`, including the fixtures;
  - any other `backend/` file, plus `agents/`, `spacetime/`, `convex/`, `firmware/`, `.github/`.
- **Build only against `contracts/fixtures/`**, with no real backend calls. Don't merge, don't open PRs, don't pull teammates' branches.
- **If a shape looks wrong**, keep the code matching the contract as written and add it to the contract questions in `frontend/PLAN.md` §7.

## Repo and branch
- `~/Downloads/WattWise` (github.com/EMP-Kritazya/WattWise). **Work only on `ashirwad`.**
- `ashirwad` is rebased onto `main` at `0dc6a34` (D1 done), so `contracts/fixtures/` and the new docs are in the branch. `main` itself is unchanged.
- The old Python simulation is deleted from the branch (D2 done). Outside `frontend/`, the branch touches only `backend/data/equipment_catalog.json`.
- Backups of the pre-rebase branch exist locally: `backup/ashirwad-before-rebase` and `backup/ashirwad-before-reword`.
- **Commit rule:** commit as Ashirwad; no AI co-author or attribution lines in commit messages.

## Where the branch stands now (before the rework)
Earlier work, built for the previous design. Much of the UI carries over; see PLAN.md §6.

- **`frontend/`:**
  - The stack: Vite, React 19, TS, Tailwind v4, hand-written shadcn/ui, Zustand, Recharts 3, react-router 7, and three.js / R3F for a 3D floor.
  - Screens in `src/pages/`: Builder (location, preferences, Claude's authority, per-unit importance), Live (3D floor, KPIs, chart, decision feed, escalation card and dialog, context strip), Agent Network, Proof (with Replay month).
  - A hand-written mock server (`src/mocks/server.ts`), a transport layer, a Zustand store, and data hooks with a SpacetimeDB / ws switch.
  - **Obsolete:** the mock server is **not** fixture-driven, and the types follow the old contract.
- **`backend/data/equipment_catalog.json`:** still Ashirwad's, but it needs the new `params` keys and `default_limits`, and `min_power_pct` removed (PLAN.md B1).

## Run
- **Node version:** 24 (via nvm).
- **In `frontend/` today:**
  - `npm run dev:mock` serves the old hand-written mock server.
  - After A3, `VITE_MOCKS=1 npm run dev` serves the fixtures.
- **Later env vars:** `VITE_API_URL`, `VITE_HUB_WS_URL`, `VITE_LIVE_TRANSPORT` (`spacetime` or `ws`), `VITE_SPACETIME_URI`, `VITE_SPACETIME_DB`.
- **Preview server:** `.claude/launch.json` in the `Assignment 3` folder has `wattwise-frontend-mock` on port 5173.

## Status right now (Oct 24, after commit `980d0a0`)
- **Done:**
  - PLAN.md written;
  - D1: `ashirwad` rebased onto `main` `0dc6a34`, force-pushed;
  - D2: old Python simulation deleted;
  - HANDOFF.md and FOR_TEAMMATES.md updated;
  - A2: contract types aligned; `ProofExtras` and its non-contract endpoint removed;
  - A3: fixture-backed REST, live rows, viewer `/ws`, Spacetime reducers and mock hub server added behind `VITE_MOCKS=1`;
  - A4: `useLive()`, `useDevices()` and `useApi()` added; every live table verified in a temporary debug route and the route removed;
  - Builder → Live smoke-tested in fixture mode;
  - `contracts/fixtures/check.py` passes all 177 files;
  - `npm run build` passes.
- **Not started:** B1–B7 (catalog, browser simulation and hub), `/sim`, and the new screen layout.
- **D3 decided by Ashirwad on Oct 24:** retain the existing 3D floor as the Simulation view.
  - Do not build a second flat appliance-tile floor.
  - Make each 3D appliance's live state obvious with a restrained glow/outline, and add the Hub, reporting links and physical
    gauges as calm overlays. Remove or soften decorative lighting/motion that competes with device state.
  - The floor continues to read only `useDevices()`; screens must not import `src/sim/` or `src/hub/`.

## Immediate next task: PLAN.md step 3 (B1 → B7 + Vitest)
1. Bring `backend/data/equipment_catalog.json` to the current EquipmentType contract and replace placeholder power figures with sourced values.
2. Build the deterministic TypeScript appliance models, seeded customer stream and one Zustand vanilla store per lane under `src/sim/`.
3. Build `src/hub/hub.ts`: apply lane Commands, step both lanes from each `sim_tick`, then return exact HubReports and one ack per Command.
4. Add Vitest and the PLAN.md §4 simulation/hub tests, including byte-identical repeated runs and exact hub totals.
5. Build `src/hub/link.ts` against `mockHubServer`, then add the `/sim` host panel in PLAN step 4.

## Active Codex implementation checkpoint (Oct 24)
Codex completed PLAN step 3 and the `/sim` host panel on `ashirwad`. Claude can take over from this checkpoint without repeating
the browser simulation or hub work.

- **Complete:** B1 catalog → B2–B5 deterministic TypeScript simulation → B6 hub → B7 link, with Vitest alongside the modules.
- **Files in scope:** `backend/data/equipment_catalog.json`, `frontend/src/sim/`, `frontend/src/hub/`, frontend test/config files.
- **Fixtures used read-only:** `contracts/fixtures/hub_protocol/*`, `contracts/fixtures/shapes/*`, and the Demo Café scenario.
- **C2 is unblocked:** retain the 3D floor for the Simulation view and add the contract-required clarity around it.
- **Gate passed:** deterministic repeated reports, exact hub totals, command ack coverage, power bounds, fixture shape compatibility,
  `npm test`, `npm run build`, and a fixture-mode browser smoke test of `/sim`.
- **Latest completed commit before this work:** `35b9656` (A2–A4 handoff update). Working-tree changes after that commit belong to
  this active checkpoint until the next handoff refresh.

### Codex checkpoint 1 — catalog + simulation core compiled
- `backend/data/equipment_catalog.json` now uses only the contract's fixed parameter shapes and removes all top-level
  `min_power_pct` fields. Source notes distinguish published criteria from explicit demo assumptions.
- Added deterministic modules under `src/sim/`: seeded customer arrivals, fixed/cycling/thermal/demand/job appliance models,
  shared room physics, command clamping/acks, and a Zustand vanilla store for each lane.
- Added `src/hub/hub.ts`, `link.ts`, and `status.ts`: the hub builds both lanes, feeds them one shared customer stream, applies
  lane commands, publishes host devices through `useDevices()`, and emits contract-shaped reports.
- `npm run build` passes at this checkpoint. Tests and the `/sim` operator surface are the next active work; do not treat this
  as the final B1–B7 handoff yet.

### Codex checkpoint 2 — B1–B7 + `/sim` complete
- Implementation commit: `ae1cbe5` (`Frontend: add deterministic browser simulation hub`).
- `src/hub/hub.test.ts` runs the entire 120-tick `server_to_hub.jsonl` fixture twice and asserts byte-identical output, exact
  totals, report shape, bounded device power, unique device IDs, and one ack per Command. It separately covers physical-floor
  clamping, delay clamping, `job_running`, `already_off`, and `unknown_device`.
- `src/pages/SimHostPage.tsx` owns the dedicated host route. In fixture mode it uses `mockHubServer`; otherwise it connects to
  `/ws/hub`. It clearly says to keep the tab open, exposes host/tick/time/mode, and shows both lanes with power, state, a subtle
  active-device glow, and every physical gauge needed by the future Simulation view.
- Browser-smoked at `http://localhost:5174/sim` with `VITE_MOCKS=1`: connected, ticks advanced, 12 devices appeared in each lane,
  and the lane totals matched their cards. The mock protocol chunk is dynamically loaded so recorded fixtures do not inflate the
  normal app entry bundle.
- Verification: `npm test` = 5 passing tests; `npm run build` passes; `contracts/fixtures/check.py` passes all 177 files and all
  174 regenerated deterministic fixtures byte-identically; `git diff --check` passes.
- **Next work is PLAN step 5.** D3 is settled: preserve the 3D floor, make its appliance states judge-readable, and layer in the
  Hub/reporting connections and physical gauges without adding distracting effects.

### Codex checkpoint 3 — fixture pause/play/reset complete
- Reported by Ashirwad: the Live pause button changed state but the fixture simulation kept advancing.
- Root cause: `VITE_MOCKS=1` returned a canned `/api/sim/control` response while `viewerWs.ts` and `liveRows.ts` each ran an
  independent interval with no control path.
- Fixed both replay sources so play, pause, reset and speed control their actual frame cadence. Play after tick 120 restarts the
  scenario instead of stopping again immediately.
- Verification: `npm test` passes 7 tests including replay-control coverage; `npm run build` passes. Browser-verified at `/live`:
  paused at 5:59 PM, stayed frozen for more than two seconds, then resumed from the same frame to 6:01 PM.

### Active Codex Toy Box checkpoint — Steps 1–5 complete
- Preserved Claude's Step 1 toon materials, ink system, palette and warm lighting.
- Device state is now intentionally sparse: ordinary running appliances do not get a floor halo; teal is reserved for a WattWise
  reduction, amber for a held job, and off devices are plain grey.
- Browser-verified at the end-of-fixture state with HVAC 2 and the water heater reduced: both had teal outlines/rings and their
  hub cables changed to teal/dashed, while ordinary appliances retained pastel bodies and red LEDs.
- Added deterministic toy diners, contract-driven visual occupancy, table `LightPool`s controlled by the lights reading and a six-person
  entrance queue for an unconsumed +40 surge request. Fixture surge updates now notify subscribers immediately while playback is paused.
- Browser-verified the full-screen floor after pressing **+40 customers** at the paused end-of-fixture state.
- Added `ToyBoxRail.tsx`: the judge-facing demo now has the semicircle With/Without/cap gauge, contract-backed demand-charge comparison,
  and live Claude status/rationale card. The duplicate KPI strip and appliance/debug sidebar are hidden in demo mode; the inspector stays
  available outside demo mode so appliance selection and owner controls are not removed.
- The default floor view now shows the complete restaurant; **Equipment focus** remains available to hide furniture on demand.
- Added the 6.5-second decision spotlight from executed `live_feed` rows: untouched appliances fade toward the background, non-target
  effects/cables quiet down, and the changed appliance gets a bright outline, cable, local light and pinned museum card.
- Browser-verified a fresh walk-in cooler decision during a 600× replay; the pin displayed only engine-provided action and peak-effect values.
- The chosen Toy Box build order is complete. The remaining known cleanup is the older drei `Html` unmount warning noted above; it is not a
  visible demo blocker, and the new decision pin does not create another `Html` root.

## Demo focus: the judging round is the priority
The live demo in judging is the main point. The app should **read as a simulation**: calm, clear, a few impactful moments.
**Don't add anything outside UI.md / ASHIRWAD.md**; make the spec'd pieces look great instead.

**The pitch (DEMO.md) shows, in order:**
1. **Agent Network:** agents report a hot evening, high prices and a Giants game.
2. **A judge taps +40 customers on their own phone.** The engine delays the dishwasher and trims HVAC; the Without lane breaks the cap while the With lane bends under it.
3. **Escalation card:** *Claude is choosing…* → *Claude chose X: rationale*.
4. **Proof tab.**

The fixture scenario matches this: surge at tick 31, escalation at tick 60, choice delivered at tick 62. That's about 1 real minute at 120×.

**Polish these five moments first:**
- the **Hub tile** pulsing each tick, with a wire to every appliance tile;
- **tiles visibly changing state** when a Command lands (dishwasher → *waiting*, HVAC → *reduced 40 %*), with live physical gauges (room temperature, dirty racks, ice level, job time left);
- the **cap line** on the two-lane chart, with Without crossing it and With staying under, plus the month peak line and the dashed forecast;
- the **escalation card** state changes, with the owner option buttons **inside the card** (no modal);
- the **agent dots** moving on Agent Network.

**Changes to the current UI:**

| Today | Change to |
|---|---|
| Live page stacks everything: context strip, escalation card, 3D floor, KPIs, three cards | Centred **`Charts \| Simulation`** toggle, plus a **right rail** (decision feed with Undo + escalation card), plus the chat drawer |
| 3D floor with camera views, Follow, demo HUD, labels toggle | **Retain it.** Simplify decorative effects; make appliances act as the live device tiles with restrained state glow, Hub/reporting links and physical gauges |
| No hub on screen, no physical gauges | Add both: "everything reports to one box" is a core story beat |
| Chart without the month peak line | Add the cap line, month peak line and dashed `with` forecast from `live_tick.forecast_kw_json` |
| No energy + cost strip | Add one from `live_tick`: energy today, price now, cost today and month, per lane |
| Escalation decided in a pop-up dialog | Buttons inside the card; `POST /api/escalations/{id}/resolve` |
| Context strip with hourly data and a sparkline | `live_context` has summaries only: show summaries and labels (contract question Q2) |
| Builder without a peak goal | Add **Minimize peak \| Hard limit** (`peak_mode`) |
| Desktop-only layout | **The phone view must work**: a judge presses +40 on their own phone (surge buttons + live view at ~375 px) |
| No `/sim` tab | Add the sim host panel; the demo laptop keeps `/sim` open |
| Proof uses the invented `ProofExtras` | Only what `BacktestResult` carries, labelled fake fixture data; keep Replay month (it's in UI.md) |

**Simulation-first look without breaking the spec:** UI.md makes Charts the default, but the toggle is remembered per viewer (localStorage). Set the demo laptop to **Simulation** once and it stays.

## Next steps
Exactly PLAN.md §5, in order:
1. D1–D3 are settled. D3 retains the 3D floor. ☑
2. Types → fixture mocks → data hooks. ☑
3. Catalog → simulation → hub → Vitest.
4. Hub link with `mockHubServer` → `/sim` panel.
5. Live (Charts | Simulation) → right rail.
6. Builder → Agent Network / Proof / chat / banners.
7. ESLint rules → §8 checklist → Static Web Apps.

## Merging later
Nothing is merged now. Integration with Suyog happens later through the hub protocol (`/ws/hub`) and REST / `/ws`; see PLAN.md §8. Ashirwad's branch should touch only his own paths, so it won't overlap Suyog's files.

## Gotchas
- **`scrollIntoView`:** in Chromium it returns a Promise. Never return it from a `useEffect`.
- **rAF timestamps:** a requestAnimationFrame timestamp can be earlier than `performance.now()`. Clamp progress at 0.
- **three.js lights:** keep them mounted and change their intensity. Shaders that can emit NaN black out the frame through Bloom.
- **Stale HMR:** after a big change, hard-reload with `?fresh=1`.
- **Edit tool:** re-read a file before using the Edit tool after a shell edit.
