# Design: UI (owner: Frontend teammate)

React + TypeScript + Vite, Tailwind, shadcn/ui, Recharts. Types generated from the API. Builds against
`src/mocks` (fake server streaming contract-shaped messages) until the real API is ready.

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
  customers/hour now.
- **Kitchen floor:** one tile per device: icon, name, live kW, state (on / reduced / waiting / running), importance badge.
  Click a tile → menu: turn on/off, start job, change importance. All tiles have a thin line to a **Hub** tile
  (the ESP32 box) that shows total kW and pulses each tick — makes "everything reports to one box" visible.
- **Two-lane chart:** total kW over the last 3 sim hours, `Without WattWise` vs `With WattWise`, plus a horizontal
  **peak cap** line and **month peak** line. Forecast for the next 2 h drawn dashed on the `with` lane.
- **KPI row:** now kW, 15-min average, month peak (both lanes), cost today (both lanes), **saved today**.
- **Decision feed:** newest first. Each item: time, device, action, explanation, effect (kW and $), Undo button.
  AI-written explanations show a small "AI" tag; templates show none.
- **Approval modal:** device, proposed action, explanation, effect, Approve / Decline. Clock shows "paused — waiting for you".
- **Warning banner:** `cap_unreachable` → "Your always-on equipment alone needs 44 kW. Raise the cap or change an importance."

### 3. Proof
- Dataset label + tariff name at the top (exact labels from DATA_AND_PROOF.md).
- 12-month table: peak kW, energy kWh, bill $ for Without / Timer / With, savings columns.
- Busiest-day chart: without vs with load, month peak marked.
- Sensitivity table, worst case highlighted.
- "Replay month" button: animates a cached month in ~15 s with three bill counters ticking.

### 4. Chat drawer (all screens)
Streaming replies. When the AI proposes a settings change, show a card with **Confirm / Cancel**; only Confirm calls the API.

## Visual language
- Colors carry meaning: always_on = grey, flexible = blue, deferrable = amber; Without lane = muted red, With lane = green;
  peak cap line = dark dashed.
- Every chart series that is simulated says so in its legend ("simulated"). Measured data doesn't exist in this version.
- Numbers: kW with 1 decimal, $ with 2 decimals.

## Performance
Ticks arrive for two lanes at ~2/s each. Keep the last 3 sim hours in state; render at most ~4 times/s.

## Done when
Builder → Live works end to end against the mock server; every message type in CONTRACTS.md is rendered;
nothing calculates numbers in the browser except formatting and the difference between the two lanes
(e.g. saved today = without cost − with cost, both straight from ticks).
