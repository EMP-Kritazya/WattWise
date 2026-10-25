# WattWise

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Keeps a restaurant's electricity peak under control without stopping service.

**Team:** Kritazya Upreti, Suyog, Ashirwad · **Event:** Cal Hacks 13.0

- Owner builds the kitchen: equipment, counts, each device's importance (always on / flexible / deferrable), a peak cap in kW, and how much Claude may decide alone.
- **Fetch.ai agents** bring live context: weather, grid prices, nearby events. Owners talk to the **Concierge** in **ASI:One**.
- A **browser simulation** (one sim host tab) models the appliances and customers; every appliance reports to one **hub** (ESP32-style controller) that talks to FastAPI over a WebSocket.
- FastAPI runs the clock (1 sim minute per tick, 120×). The **engine** computes every number from the hub's state and, every 5 simulated minutes, sends commands back through the hub inside the owner's rules.
- When no in-rules move can hold the cap, the engine applies the safest option within the owner's limits at once and offers up to 3 evaluated alternatives; **Claude** may choose another, which the engine revalidates against the owner's authority; an unauthorized or late choice is rejected and the safe fallback stays active.
- Every screen updates live from **SpacetimeDB**: energy, current price and cost, every appliance's state.
- Every viewer sees the same live kitchen through **SpacetimeDB**. Records and the ESP32 bridge live in **Convex**. It runs on **Microsoft Azure**.
- Proof: a year of DOE-calibrated restaurant data replayed on a real tariff — without vs. timer vs. WattWise.

## Run the connected application

Use Python 3.11 and Node.js. Run these commands from the repository root. Copy
`.env.example` to `.env`, replace `AGENT_TOKEN` and `FETCH_AGENT_SEED` with private
values, and keep the same values in every process. The example runs the **real
engine**, browser simulation, memory store, and WebSocket live fallback. External
AI and hardware are optional.

```sh
cp .env.example .env
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
backend/.venv/bin/python -m pip install -r agents/requirements.txt
npm --prefix frontend ci
```

Start the API in one terminal. Settings are environment variables; the backend
does not automatically read `.env`.

```sh
set -a
source .env
set +a
cd backend
.venv/bin/uvicorn api.main:app --reload
```

Start the frontend in another terminal. These settings explicitly connect to the
API instead of using fixture screens. Vite proxies `/api`, `/ws`, and `/ws/hub`
to port 8000; set `API_TARGET` if your backend uses another address.

```sh
VITE_MOCKS=0 VITE_LIVE_TRANSPORT=ws npm --prefix frontend run dev
```

Open the frontend URL printed by Vite, build a kitchen, then keep exactly one
`/sim` tab open and press Play. The `/sim` tab runs the appliances; other tabs are
viewers. The API owns time and forwards hub reports into both engine lanes.
Engine commands go back to the hub on the following tick, and viewers receive
the computed energy, costs, decisions, and comparison. Without a sim host the
clock waits. The catalog and selected tariff are served by the backend; the demo
tariff is illustrative and must not be presented as a real utility saving.
To show real billed amounts, install the PG&E URDB data described in
`docs/design/DATA_AND_PROOF.md` and set frontend
`VITE_TARIFF_ID=pge_b19_secondary_voluntary` before starting Vite.
Calibrated warm-up requires the optional ComStock dataset. When the current
recipe exceeds catalog ratings, the runtime logs the problem and uses explicitly
labelled synthetic fixture history; it never clips those readings.

### Fetch context and ASI:One

For a reproducible demo, leave `DEMO_MODE=1` and the example July simulation
start. In **four separate terminals**, load the root `.env` as above and run one
of these commands per terminal:

```sh
backend/.venv/bin/python agents/weather.py --recorded
backend/.venv/bin/python agents/grid.py --recorded
backend/.venv/bin/python agents/events.py --recorded
backend/.venv/bin/python agents/concierge.py --recorded
```

All four agents need working uAgents transport. Follow
[Agentverse registration](agents/REGISTRATION.md) to connect their mailboxes;
starting a process alone does not complete mailbox registration. The Concierge
posts authenticated structured context to the API after detecting a kitchen
build and every `CONTEXT_INTERVAL_S` real seconds. The shared `AGENT_TOKEN`
authenticates context and agent-log posts. Recorded labels remain visible. This
runs real engine decisions with recorded external context, not canned decisions.

For live sources, set `DEMO_MODE=0`, remove `--recorded`, and set `SIM_START_TS`
to a timezone-aware UTC timestamp on the current service day. Weather and grid
responses use actual source timestamps and are matched against simulation time;
the accelerated simulation can eventually outrun their forecast window. Weather
uses Open-Meteo. Grid uses CAISO and falls back to explicitly recorded prices
when CAISO fails. **Typed event context currently stays recorded**, because
Ticketmaster does not publish the contract's required attendance field. A
`TICKETMASTER_API_KEY` enables live event listings in public agent chat only.
An unavailable source does not stop the kitchen.

Set `ANTHROPIC_API_KEY` and an available `ANTHROPIC_MODEL` for Claude escalation
choices and crowd classification. Without a key, routine engine decisions and
safe escalation fallbacks still run; chat uses its available fallback. Set
`ASI1_API_KEY` / `ASI1_MODEL` for the optional ASI:One model fallback. Open ASI:One
to chat with the registered Concierge after registration.

### SpacetimeDB and optional services

For shared live tables, deploy the module in `spacetime/` and set backend
`LIVE_TRANSPORT=spacetime`, `SPACETIMEDB_URL`, `SPACETIMEDB_DB`, and the runtime
identity `SPACETIMEDB_TOKEN`. Set frontend `VITE_LIVE_TRANSPORT=spacetime`,
`VITE_SPACETIME_URI` (the WebSocket URI), and `VITE_SPACETIME_DB` in
`frontend/.env.local`, then restart Vite. Use only a viewer identity for the
optional browser token; never expose the runtime token. `/ws` still carries chat
and supplies the live fallback when configured services are unavailable.

`STORE=convex` with `CONVEX_URL` enables durable records; see
[Convex setup](convex/README.md). `HARDWARE=off` is the browser-only application;
optional hardware setup is in [firmware/README.md](firmware/README.md). Memory
records disappear on backend restart. Do not start multiple backend workers:
one process owns the application clock.

### Verify the integration

```sh
cd backend
.venv/bin/python -m pytest tests/integration -q
```

The integration test runs the production Concierge context loop with recorded
source replies through the real API, engine, runtime, hub protocol, and viewer
WebSocket. It checks authenticated context reaching both lanes, command delivery
on the next tick, automatic engine decisions, and live UI message shapes. Its
hub is a protocol-level test client; frontend physics and rendering have separate
checks:

```sh
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

## Fetch.ai agents (Innovation Lab)
| Agent | Address | Protocols |
|---|---|---|
| WattWise Concierge | `agent1q...` (fill in) | Agent Chat Protocol (ASI:One) |
| Weather Agent | `agent1q...` | WeatherRequest / WeatherResponse |
| Grid Agent | `agent1q...` | PriceRequest / PriceResponse |
| Events Agent | `agent1q...` | EventsRequest / EventsResponse |
Try it: open ASI:One and ask "What will lunch cost me today?"

## Deploy (Microsoft Azure)
`backend` (API + runtime + engine) and `agents` on Azure Container Apps, each **min = max replicas = 1**.
Frontend: Azure Static Web Apps. SpacetimeDB and Convex: hosted clouds. Steps: `docs/design/AZURE.md`.

Start with `CLAUDE.md`, then `docs/PRINCIPLES.md`, `docs/ARCHITECTURE.md` and your file in `docs/team/`.

Data credits: NREL ComStock End-Use Load Profiles · OpenEI Utility Rate Database · FSTC / ENERGY STAR appliance data.
