# Design: UI (owners: Ashirwad for screens · Suyog for data layer, mocks and chat)

Split by folder to avoid merge conflicts: Suyog owns `src/data/`, `src/mocks/`, generated `src/types/` and
`src/features/chat/`. Ashirwad owns `src/features/builder/`, `live/`, `feed/`, `proof/` and `src/components/`.
Screens read data only through Suyog's hooks, so the SpacetimeDB / `/ws` switch never touches a screen.

React + TypeScript + Vite, Tailwind, shadcn/ui, Recharts. Types generated from the API (OpenAPI + ws schema), plus
SpacetimeDB generated bindings and Convex generated types. Builds against `src/mocks` (fake server streaming
contract-shaped messages) until the real API is ready. Hosted on Azure Static Web Apps.

**Where live data comes from.** With `LIVE_TRANSPORT=spacetime` (default) the Live screen subscribes to SpacetimeDB
tables (`live_tick`, `tick_history`, `live_device`, `live_comparison`, `live_feed`, `live_clock`), so every viewer sees the
same kitchen. REST is used for config, clicks, approvals, proposals and chat; `/ws` carries chat streaming, approvals and
proposals. With `LIVE_TRANSPORT=ws` everything comes over `/ws` (offline fallback). One data hook hides the switch.

## Screens
### 1. Kitchen Builder (setup)
- **Equipment list** from `GET /api/catalog`, grouped by category. Each row: name, rated kW, count stepper (0–5).
- **Per device importance** (after counts are set, each unit is listed): segmented control
  `Always on | Flexible | Deferrable`, with its limits shown inline:
  flexible → min power % slider + max minutes; deferrable → max delay minutes + finish-by time.
- **Peak cap** slider/input in **kW**, with a helper line: "Your highest 15-minute average power. Demand charges are based on this."
- Operating hours, tariff (preset dropdown), seed (hidden in demo mode).
- "Build kitchen" → `POST /api/kitchen` → shows a short "warming up 21 days of history…" state → Live screen.

### 2. Live Simulation (the main demo screen)
Layout: top bar · kitchen floor (left, ~60%) · charts + feed (right, ~40%) · chat drawer (slide-in).
- **Top bar:** sim clock + day, play/pause, speed (1× / 30× / 120× / 600×), `+20 customers` and `+40 customers` buttons,
  customers/hour now. Surge buttons call the SpacetimeDB reducer `request_surge` so a judge's phone can add customers to
  the shared kitchen (REST `/api/events/customers` when `LIVE_TRANSPORT=ws`).
- **Kitchen floor:** one tile per device: icon, name, live kW, state (on / reduced / waiting / running), importance badge.
  Click a tile → menu: turn on/off, start job, change importance. All tiles have a thin line to a **Hub** tile
  (the ESP32 box) that shows total kW and pulses each tick — makes "everything reports to one box" visible.
  With `HARDWARE=esp32`, the Hub tile shows online/offline and mapped tiles carry a small "hardware" badge.
- **Two-lane chart:** total kW over the last 3 sim hours, `Without WattWise` vs `With WattWise`, plus a horizontal
  **peak cap** line and **month peak** line. Forecast for the next 2 h drawn dashed on the `with` lane.
- **KPI row:** now kW, 15-min average, month peak (both lanes), cost today (both lanes), **saved today** and peak avoided
  (both from `LaneComparison`, never computed in the browser).
- **Decision feed:** newest first. Each item: time, device, action, explanation, effect (kW and $), Undo button.
  AI-written explanations show a small "AI" tag; templates show none.
- **Approval modal:** device, proposed action, explanation, effect, Approve / Decline. Clock shows "paused — waiting for you".
- **Warning banners:** `hub_offline`, `live_transport_down`, `store_down` show a short plain message.
  `cap_unreachable` → "Your always-on equipment alone needs 44 kW. Raise the cap or change an importance."

### 3. Proof
- Dataset label + tariff name at the top (exact labels from DATA_AND_PROOF.md).
- 12-month table: peak kW, energy kWh, bill $ for Without / Timer / With, savings columns. January marked "partial (warm-up)".
- Busiest-day chart: without vs with load, month peak marked.
- Sensitivity table, worst case highlighted.
- "Replay month" button: animates a cached month in ~15 s with three bill counters ticking.

### 4. Chat drawer (all screens)
Streaming replies. When the AI creates a Proposal (`proposal` message), show a card with **Confirm / Cancel**;
only Confirm calls `POST /api/proposals/{id}/confirm`. ASI:One is the primary chat door (Fetch.ai); this drawer is the
second door to the same agent, so proposals confirmed in ASI:One disappear here too.

## Visual language
- Colors carry meaning: always_on = grey, flexible = blue, deferrable = amber; Without lane = muted red, With lane = green;
  peak cap line = dark dashed.
- Every chart series that is simulated says so in its legend ("simulated"). Devices fed by a real ESP32 show "measured (scaled)"; nothing simulated is ever shown as measured.
- Numbers: kW with 1 decimal, $ with 2 decimals.

## Performance
Ticks arrive for two lanes at ~2/s each. Keep the last 3 sim hours in state; render at most ~4 times/s.

## Done when
Builder → Live works end to end against the mock server; every message type in CONTRACTS.md is rendered;
nothing calculates numbers in the browser except formatting (saved today and peak avoided come from `LaneComparison`);
the Live screen works over both SpacetimeDB and `/ws`.
