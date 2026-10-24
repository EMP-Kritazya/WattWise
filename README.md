# WattWise

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Keeps a restaurant's electricity peak under control without stopping service.

**Team:** Kritazya Upreti, Suyog, Ashirwad · **Event:** Cal Hacks 13.0

- Owner builds the kitchen: picks equipment, counts, each device's importance (always on / flexible / deferrable) and a peak cap in kW.
- Every device reports to one hub box (simulated ESP32; optionally a real ESP32 through Convex). The engine forecasts, decides and acts inside the owner's rules.
- Claude explains every decision, answers questions and proposes changes; it never decides, and nothing it proposes applies until the owner confirms.
- Owners talk to it in **ASI:One** through our Fetch.ai agent, or in the dashboard chat. Every viewer sees the same live kitchen through **SpacetimeDB**. Records and the ESP32 bridge live in **Convex**. It runs on **Microsoft Azure**.
- Proof: replay of historical restaurant data with vs. without WattWise on a real tariff.

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
| `LIVE_TRANSPORT` | `spacetime` (default) \| `ws` (offline fallback) |
| `SPACETIMEDB_URL`, `SPACETIMEDB_DB`, `SPACETIMEDB_TOKEN` | SpacetimeDB (runtime identity) |
| `STORE` | `convex` (default) \| `memory` |
| `CONVEX_URL` | Convex deployment (`https://<name>.convex.cloud`) |
| `HARDWARE` | `off` (default) \| `esp32` |
| `FETCH_AGENT_SEED`, `AGENTVERSE_API_KEY` | Fetch.ai uAgent identity and Agentverse mailbox |

## Fetch.ai agent
| Field | Value |
|---|---|
| Name | WattWise Concierge (fill in after registration) |
| Address | `agent1q...` (fill in after registration) |
| Protocols | Agent Chat Protocol (ASI:One discoverable) |
| Try it | Open ASI:One and ask "What will lunch cost me today?" |

## Deploy (Microsoft Azure)
API + run loop + uAgent: one container on Azure Container Apps with **min = max replicas = 1** (state is in memory).
Frontend: Azure Static Web Apps. SpacetimeDB and Convex: hosted clouds. Steps: `docs/design/INTEGRATIONS.md`.

Start with `CLAUDE.md`, then `docs/ARCHITECTURE.md`. Claude Code users: `docs/CLAUDE_CODE_PHASES.md`.

Data credits: NREL ComStock End-Use Load Profiles · OpenEI Utility Rate Database · FSTC / ENERGY STAR appliance data.
