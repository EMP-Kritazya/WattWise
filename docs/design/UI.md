# Design: UI (owner: Ashirwad)

## Principles
- Show, don't compute: formatting only; lane differences come from `LaneComparison`.
- Live by subscription (SpacetimeDB); one hook switches to `/ws` for the offline fallback.
- Make the invisible visible: hub, agents talking, Claude's choice, the cap line.
- Honest labels on every data source; every action shows pending until the live row changes.

Ashirwad owns all of `frontend/`. Screens read data only through hooks in `src/data/`, so the SpacetimeDB / `/ws`
switch never touches a screen. Suyog reviews the hooks against the API; Kritazya provides the SpacetimeDB bindings.

React + TypeScript + Vite, Tailwind, shadcn/ui, Recharts. Types generated from the API (OpenAPI + ws schema), plus
SpacetimeDB generated bindings and Convex generated types. Builds against `src/mocks` (fake server streaming
contract-shaped messages) until the real API is ready. Hosted on Azure Static Web Apps.

**Two halves of `frontend/`, kept apart.** `src/sim/` + `src/hub/` (SIMULATION.md) run only in the sim host tab (`/sim`) and talk
only to FastAPI over `/ws/hub`. Screens never import them directly. The one bridge is the hook `src/data/useDevices()`: in the sim
host tab it returns the hub's current `Device[]` (the appliances' React state, re-rendering on every applied Command); in every
other tab it returns the `live_device` rows. Both are the same Device shape, so the Simulation view is one set of components.
Charts, KPIs, energy and cost always come from SpacetimeDB in every tab (they are engine numbers, not appliance state).

**Where live data comes from.** With `LIVE_TRANSPORT=spacetime` (default) screens subscribe to SpacetimeDB tables (`live_tick`,
`tick_history`, `live_device`, `live_comparison`, `live_feed`, `live_clock`, `live_context`, `live_escalation`, `live_agent_log`):
energy, current price, cost today/month, peaks, every device's state and physical gauges, decisions, escalations. Updates arrive
as the runtime publishes each tick (≈ 2 per second at 120×). REST is used for config, clicks, escalation choices, proposals and
chat; `/ws` carries chat streaming and proposals. With `LIVE_TRANSPORT=ws` everything comes over `/ws` (offline fallback).
One data hook hides the switch. Until the backend exists, `src/mocks` serves the shared fixtures (`contracts/fixtures/`).

## Screens
### 1. Kitchen Builder (setup)
- **Equipment list** from `GET /api/catalog`, grouped by category. Each row: name, rated kW, count stepper (0–5).
- **Per device importance** (after counts are set, each unit is listed): segmented control
  `Always on | Flexible | Deferrable`, with its limits shown inline:
  flexible → min power % slider + max minutes; deferrable → max delay minutes + finish-by time.
- **Peak goal**: segmented control `Minimize peak | Hard limit`. *Minimize* → no number, the engine keeps the month's peak as low as
  the rules allow. *Hard limit* → slider/input in **kW**, helper line: "Your highest 15-minute average power. Demand charges are based on this."
  Sends `peak_mode` + `peak_cap_kw` (CONTRACTS.md KitchenConfig).
- Location (preset "Marina, San Francisco"), owner preferences (free text), operating hours, tariff (preset), seed (hidden in demo mode).
- **Claude's authority**: toggle + max cap overrun (kW), max extra delay (min), max extra reduce (min); food-safety note ("never below 50 % for refrigeration, whatever you set").
- "Build kitchen" → `POST /api/kitchen` → shows a short "warming up 21 days of history…" state → Live screen.

### 2. Live Simulation (the main demo screen)
Layout: top bar · a centred **view toggle `Charts | Simulation`** · the selected view · decision feed + escalation card (right rail) ·
chat drawer (slide-in). The toggle is a per-viewer preference (remembered locally); both views stay subscribed so switching is instant.
- **Charts view** (default): two-lane chart, forecast, KPI row, energy + cost strip, context strip — all from SpacetimeDB, updating
  live every tick.
- **Simulation view**: the kitchen floor below. In the sim host tab it renders the appliances' own React state (the hub's current
  state, re-rendering when a Command changes it); in every other tab the same components render the `live_device` rows.
- **Top bar:** sim clock + day, play/pause, speed (1× / 30× / 120× / 600×), `+20 customers` and `+40 customers` buttons,
  customers/hour now. Surge buttons call the SpacetimeDB reducer `request_surge` so a judge's phone can add customers to
  the shared kitchen (REST `/api/events/customers` when `LIVE_TRANSPORT=ws`).
- **Kitchen floor (Simulation view, from `useDevices()`):** one tile per device: icon, name, live kW, % of rated, state (on / reduced / waiting / running), importance badge,
  and the device's `physical` gauge when present (indoor temp, box temp, dirty racks, ice level, job remaining).
- **Energy + cost strip (from `live_tick`):** energy today (kWh), current price ($/kWh), cost today and this month ($), per lane.
- **Sim host panel (`/sim` only):** hub connection state, last `tick_id`, ticks behind, "another sim host is running" when refused.
  Click a tile → menu: turn on/off, start job, change importance. All tiles have a thin line to a **Hub** tile
  (the ESP32 box) that shows total kW and pulses each tick — makes "everything reports to one box" visible.
  With `HARDWARE=esp32`, the Hub tile shows online/offline and mapped tiles carry a small "hardware" badge.
- **Two-lane chart:** total kW over the last 3 sim hours, `Without WattWise` vs `With WattWise`, plus a horizontal
  **peak cap** line and **month peak** line. Forecast for the next 2 h drawn dashed on the `with` lane.
- **KPI row:** now kW, 15-min average, month peak (both lanes), cost today (both lanes), **saved today** and peak avoided
  (both from `LaneComparison`, never computed in the browser).
- **Decision feed:** newest first. Each item: time, device, action, explanation, effect (kW and $), Undo button.
  AI-written explanations show a small "AI" tag; templates show none.
- **Context strip:** outdoor temp now and next hours, price now + sparkline + stress, nearby events, crowd effect; each with its label.
- **Escalation card:** problem (forecast peak vs cap), options with engine numbers and rule breaks, `within authority` badges.
  States: *Claude is choosing…* → *Claude chose X: rationale* (or *Waiting for you* with option buttons when outside authority,
  or *Default applied* at the deadline). Clock shows "paused — escalation" in demo mode.
- **Warning banners:** `hub_offline`, `live_transport_down`, `store_down` show a short plain message.
  `cap_unreachable` → "Your always-on equipment alone needs 44 kW. Raise the cap or change an importance."

### 3. Agent Network
Live graph: Concierge in the centre, Weather / Grid / Events agents around it, Claude and the WattWise engine as nodes.
Each `live_agent_log` row animates along its edge with its summary; list of the last 50 messages beside it.

### 4. Proof
- Dataset label + tariff name at the top (exact labels from DATA_AND_PROOF.md).
- 12-month table: peak kW, energy kWh, bill $ for Without / Timer / With, savings columns. January marked "partial (warm-up)".
- Busiest-day chart: without vs with load, month peak marked.
- Sensitivity table, worst case highlighted.
- "Replay month" button: animates a cached month in ~15 s with three bill counters ticking.

### 5. Chat drawer (all screens)
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
Builder → Live works end to end against the mocks (live rows + REST from the shared fixtures, and the simulation driven by
`mockHubServer`); every message type in CONTRACTS.md is rendered; no screen imports `src/sim` or `src/hub`;
nothing calculates numbers in the browser except formatting (saved today and peak avoided come from `LaneComparison`);
the Live screen works over both SpacetimeDB and `/ws`.
