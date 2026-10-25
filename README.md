# WattWise

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Keeps a restaurant's electricity peak under control without stopping service.

**Team:** Kritazya Upreti, Suyog, Ashirwad · **Event:** Cal Hacks 13.0

- Owner builds the kitchen: equipment, counts, each device's importance (always on / flexible / deferrable), a peak cap in kW, and how much Claude may decide alone.
- **Fetch.ai agents** bring live context: weather, grid prices, nearby events. Owners talk to the **Concierge** in **ASI:One**.
- A **browser simulation** (one sim host tab) models the appliances and customers; every appliance reports to one **hub** (ESP32-style controller) that talks to FastAPI over a WebSocket.
- FastAPI runs the clock (1 sim minute per tick, 120×). The **engine** computes every number from the hub's state and, every 5 simulated minutes, sends commands back through the hub inside the owner's rules.
- When no in-rules move can hold the cap, the engine applies the safest option within the owner's limits at once and offers up to 3 evaluated alternatives; **Claude** may choose another, which the engine revalidates against the owner's authority; beyond it, the owner confirms.
- Every screen updates live from **SpacetimeDB**: energy, current price and cost, every appliance's state.
- Every viewer sees the same live kitchen through **SpacetimeDB**. Records and the ESP32 bridge live in **Convex**. It runs on **Microsoft Azure**.
- Proof: a year of DOE-calibrated restaurant data replayed on a real tariff — without vs. timer vs. WattWise.

## Run
> Fill in during the hackathon.
```
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn api.main:app --reload
cd frontend && npm install && npm run dev
```
`.env` (never committed; copy `.env.example`):
| Variable | Values |
|---|---|
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Claude |
| `KITCHEN_IMPL` | `fake` \| `real` |
| `DEMO_MODE` | `1` for the identical demo run |
| `HUB_IMPL` | `browser` (default, the `/sim` tab) \| `fake` (fixture sim host, no browser) |
| `CONTEXT_INTERVAL_S` | seconds between Fetch context refreshes (default 600) |
| `LIVE_TRANSPORT` | `spacetime` (default) \| `ws` (offline fallback) |
| `SPACETIMEDB_URL`, `SPACETIMEDB_DB`, `SPACETIMEDB_TOKEN` | SpacetimeDB (runtime identity) |
| `STORE` | `convex` (default) \| `memory` |
| `CONVEX_URL` | Convex deployment (`https://<name>.convex.cloud`) |
| `HARDWARE` | `off` (default) \| `sim_bridge` \| `esp32` |
| `CLAUDE_PROVIDER` | `anthropic` (default) \| `foundry` |
| `AGENT_TOKEN` | shared secret for agent → API calls |
| `FETCH_AGENT_SEED`, `AGENTVERSE_API_KEY` | Fetch.ai uAgent identity and Agentverse mailbox |

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
