# Handoff prompt (paste into ChatGPT or a new Claude session)

You are taking over Ashirwad's work on **WattWise** (Cal Hacks 13.0, Oct 23–25 2026). Work carefully, keep the existing code style,
and run `npm run build` and `npm test` (in `frontend/`) before calling anything done.

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
- **Waiting on Ashirwad: D3**, what the Simulation view draws.
  - Recommended: the tile floor per UI.md (a tile per device, wired to a pulsing Hub tile, with physical gauges).
  - Or: also keep the existing 3D floor as an optional look that reads only `useDevices()`.
  - Ask him before building C2's Simulation view. Steps A and B don't depend on it.

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
- **Do not start C2 screen redesign yet:** D3 (tile simulation view versus retaining optional 3D) is still Ashirwad's decision.
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
- **Next work is PLAN step 5, but D3 is still a user decision.** Do not replace the Live page's current floor until Ashirwad
  confirms whether the contract-specified wired device tiles replace it entirely or the 3D floor remains as an optional view.

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
| 3D floor with camera views, Follow, demo HUD, labels toggle | **Not in the spec.** The Simulation view is appliance **tiles wired to a Hub tile** (decision D3; ask Ashirwad before keeping any 3D) |
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
1. Settle D3 (D1 and D2 are done).
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
