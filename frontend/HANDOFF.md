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
- `ashirwad` is still based on the older `main` commit `cb0d598`. The new docs and fixtures are on `main` at `0dc6a34`.
- **Decision D1 in PLAN.md** (rebase onto `main`) must be made before coding against the fixtures. Until then, read new files with `git show origin/main:<path>`.
- **Commit rule:** no Claude co-author line on commits.

## Where the branch stands now (before the rework)
Earlier work, built for the previous design. Much of the UI carries over; see PLAN.md §6.

- **`frontend/`:**
  - The stack: Vite, React 19, TS, Tailwind v4, hand-written shadcn/ui, Zustand, Recharts 3, react-router 7, and three.js / R3F for a 3D floor.
  - Screens in `src/pages/`: Builder (location, preferences, Claude's authority, per-unit importance), Live (3D floor, KPIs, chart, decision feed, escalation card and dialog, context strip), Agent Network, Proof (with Replay month).
  - A hand-written mock server (`src/mocks/server.ts`), a transport layer, a Zustand store, and data hooks with a SpacetimeDB / ws switch.
  - **Obsolete:** the mock server is **not** fixture-driven, and the types follow the old contract.
- **`backend/engine/{devices,hub,customers,fake_hub}.py` and `backend/tests/simulation/`:** the old Python simulation. It is **now outside Ashirwad's scope** and is replaced by TypeScript; removing it is decision D2 in PLAN.md.
- **`backend/data/equipment_catalog.json`:** still Ashirwad's, but it needs the new `params` keys and `default_limits`, and `min_power_pct` removed (PLAN.md B1).

## Run
- **Node version:** 24 (via nvm).
- **In `frontend/` today:**
  - `npm run dev:mock` serves the old hand-written mock server.
  - After A3, `VITE_MOCKS=1 npm run dev` serves the fixtures.
- **Later env vars:** `VITE_API_URL`, `VITE_HUB_WS_URL`, `VITE_LIVE_TRANSPORT` (`spacetime` or `ws`), `VITE_SPACETIME_URI`, `VITE_SPACETIME_DB`.
- **Preview server:** `.claude/launch.json` in the `Assignment 3` folder has `wattwise-frontend-mock` on port 5173.

## Next steps
Exactly PLAN.md §5, in order:
1. Settle D1, D2, D3.
2. Types → fixture mocks → data hooks.
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
