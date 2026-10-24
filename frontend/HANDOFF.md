# Handoff prompt (paste into ChatGPT or a new Claude session)

You are taking over frontend work on **WattWise** (Cal Hacks 13.0, Oct 23–25 2026). Work carefully, keep the existing code style, and run `npx tsc -b` after every change.

## Project
WattWise keeps a restaurant's electricity peak (demand charges = highest 15-minute average kW of the month) under an owner-set cap. A simulated kitchen reports to one simulated ESP32 "hub"; a Python engine (teammate Kritazya) decides and acts inside the owner's rules (importance: always_on / flexible / deferrable); Claude only explains and chats, never decides or computes numbers. Two "lanes" run side by side: `without` vs `with` WattWise. Read `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `docs/design/UI.md` first.

## Repo
`~/Downloads/WattWise` (github.com/EMP-Kritazya/WattWise). **All my work is on branch `ashirwad/frontend` — never commit to main; only commit/push when I ask.** Everything in `frontend/` is currently uncommitted.

## Run (in `frontend/`, Node 24 via nvm)
- `npm run dev:mock` — in-browser fake server, no backend → http://localhost:5173 (Kitchen Builder → Build kitchen → Live)
- `npm run dev` — real FastAPI on :8000 (Vite proxies `/api`, `/ws`)
- `npm run build` must pass

## Stack
React 19 + TS + Vite 7, Tailwind v4, shadcn/ui (hand-written in `src/components/ui`), Zustand, Recharts 3, react-router 7, three.js 0.186 + @react-three/fiber 9 + @react-three/drei 10 + @react-three/postprocessing 3.

## Architecture (done and working)
- `src/types/contracts.ts` — STUB types transcribed from CONTRACTS.md (replace with `npm run gen:types` once the schema/OpenAPI exist).
- `src/transport/` — `Transport` interface (one method per REST endpoint + `/ws` subscribe); `real.ts` = FastAPI client. `src/mocks/server.ts` = seeded fake server (ticks for both lanes, decisions, approvals that pause the clock, warnings, streaming chat, backtest).
- `src/store/sim.ts` (Zustand) + `ingest.ts` (buffers `/ws`, flushes 4×/s).
- Live page: SimControls → **3D LiveFloor (hero)** → KpiRow → DevicePowerCard / PowerTrendCard / DecisionFeed; AssistantPanel docked right on xl; ApprovalDialog modal. Dark theme.
- 3D floor in `src/components/live/floor/`:
  - `LiveFloor.tsx` — orthographic isometric Canvas, lights, Environment, Bloom/Vignette/ToneMapping, custom `CameraRig` (fits projected boxes inside the HUD-free area; flies to the device of each new decision when "Follow" is on), modes `with` / `without` / `compare` (side by side: stacked on narrow canvases, in a row on wide), **demo mode** (full screen; keys Space play/pause, C +40 customers, S side by side, F follow, Esc exit), HUD.
  - `Restaurant.tsx` (one lane), `Device3D.tsx` (equipment models, status LED, load glow, tags, hover, `DeviceDetails` panel), `Ambient.tsx` (energy particles to hub, Hub3D, seated Diners, pendant Lamps with light cones/pools, CapOutline red when over cap, LaneTitle), `Scenery.tsx` (textured floors, walls, framed windows, props, mounts Diorama + Furniture), `Diorama.tsx` (earth slab, sidewalk, grass, fence, trees, street lamps, benches), `Furniture.tsx` (instanced tables/chairs/place settings, bar + backlit bottles, range hood, shelves, pass with heat lamps, office), `Staff.tsx` (2 chefs + waiters walking aisles), `Effects3D.tsx` (LightCone/LightPool, standard materials only), `textures.ts` (procedural canvas textures), `plan.ts` (layout), `palette.ts`, `Hud.tsx` (PeakMeter, DecisionToast, DemoBar).

## Also done (latest)
- **Camera views** in the floor HUD: Isometric, Top-down (orthographic, via `CameraRig` with a target direction; OrbitControls limits are applied per view on arrival), Street and POV (drei `<PerspectiveCamera makeDefault>` + `PerspectiveRig` fly-in). Side by side only allows the two orthographic views; Follow is disabled in perspective views.
- **Labels toggle** (HUD button, demo key `L`): hides kW tags, action tags, hub card, cap badge and room names; hover/click details still work.
- Demo keys: Space play/pause · C +40 customers · S side by side · V cycle views · L labels · F follow · Esc exit.
- `npm run build` passes; all views checked in the browser.

## Next tasks (in order)
1. Polish: POV could get a gentle idle sway; the Street/POV poses are in `POSES` in `LiveFloor.tsx` if framing needs tuning.
2. N8AO ambient occlusion and drei `SoftShadows` were tried and made the frame black/blank in this setup — leave them out unless verified working.
3. Check speed on the presenting laptop (Canvas `dpr` is [1, 1.75]; lower it if the frame rate drops); test normal, side-by-side and demo modes end to end.
4. Phase 1–2 items still open in `docs/TASKS.md`: Builder per-unit importance + limits, chat Confirm cards (blocked on a contract message), Proof screen (Phase 4).
5. Commit to `ashirwad/frontend` when I say so.

## Rules (CLAUDE.md / UI.md)
- UI computes no numbers except formatting and "saved today" = without cost − with cost (visual-only ratios like glow or bar width are fine, never displayed).
- Everything simulated is labeled "simulated". kW 1 decimal, $ 2 decimals.
- Colors carry meaning: always_on grey, flexible blue, deferrable amber; Without lane red, With lane green.
- Never hand-write contract shapes; don't change `docs/CONTRACTS.md` without the team.

## Open contract gaps (raise with the team)
No `/ws` message for AI proposals (chat Confirm cards) · Proof data missing (busiest-day series, tariff name, sensitivity, replay series, cached run lookup) · no tariff list endpoint · `forecast_kw` start/length unclear · no state replay on `/ws` connect · no "warning cleared" message · importance is per equipment type, not per unit.

## Gotchas
- In Chromium `scrollIntoView` returns a Promise — never return it from a `useEffect`.
- drei `<Html>` labels use z-index up to 60; the HUD sits at `z-[80]`.
- Mounting/unmounting three.js lights forces shader recompiles: keep lights mounted and change intensity.
- Custom shaders that can emit NaN black out the whole frame through Bloom — prefer standard materials.
