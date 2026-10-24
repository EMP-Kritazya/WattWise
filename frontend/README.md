# WattWise frontend

React + TypeScript + Vite, Tailwind v4, shadcn/ui, Recharts, Zustand. Owner: Ashirwad. Spec: `docs/design/UI.md`.

## Run
```
npm install
npm run dev:mocks  # fixture mode: serves contracts/fixtures/ in the browser, no backend needed
npm run dev        # real FastAPI server; Vite proxies /api and /ws to http://localhost:8000 (override with API_TARGET)
npm run build      # type-check + production build; run before calling anything done
```
Needs Node 20.19+ (Vite 7).

## Layout
| Path | What |
|---|---|
| `src/types/` | Contract types. `contracts.ts` is a **STUB** transcribed from `docs/CONTRACTS.md`; replace with generated types (below) |
| `src/transport/` | One `Transport` interface: a method per REST endpoint + the `/ws` stream. `real.ts` talks to FastAPI |
| `src/mocks/` | The same interface, served from `contracts/fixtures/` (REST, viewer `/ws`, SpacetimeDB rows, mock `/ws/hub` server) |
| `src/store/` | Zustand store. `ingest.ts` buffers `/ws` messages and flushes 4×/s |
| `src/pages/` | Builder, Live, Proof |
| `src/components/live/` | Top bar, kitchen floor + hub, KPI row, two-lane chart, decision feed, approval dialog, warning banner |
| `src/components/ui/` | shadcn/ui components (`npx shadcn@latest add <name>` for more) |

## Live floor (3D) and demo mode
`src/components/live/floor/` is a React Three Fiber scene of the restaurant: devices glow with their live load, energy
particles stream to the hub, diners follow customers/hour, and the camera flies to each decision ("Follow").
"Side by side" shows both lanes at once (stacked on narrow screens, in a row on wide ones).

**Demo mode** (button on the floor) goes full screen with a presenter bar. Shortcuts: `Space` play/pause ·
`C` +40 customers · `S` side by side · `F` follow decisions · `Esc` exit. Rehearse on the presenting laptop: it needs WebGL.

## Types
Never hand-write contract types. When `contracts/ws_messages.schema.json` and the API's `/openapi.json` exist:
```
npm run gen:types
```
then point `src/types/index.ts` at `src/types/generated/` and delete `src/types/contracts.ts`.

## Rules (from CLAUDE.md / UI.md)
- The UI computes nothing except formatting and "saved today" (without cost − with cost, both from ticks).
- Every simulated series says "simulated". kW to 1 decimal, $ to 2.
- Colors carry meaning: always_on grey, flexible blue, deferrable amber; Without lane red, With lane green.
