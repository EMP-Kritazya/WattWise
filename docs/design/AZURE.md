# Design: Microsoft Azure (owners: Kritazya for Container Apps · Ashirwad for Static Web Apps)

## Principles
- Azure runs what genuinely needs the cloud: always-on agents, a public URL, secrets, monitoring.
- Stateful backend → exactly one replica (min = max = 1); scale-to-zero or scale-out would break lanes and the run loop.
- Walking skeleton early (Phase 1), so later deploys are routine. Same containers locally (`docker compose`) as the fallback.

## Map
| Piece | Service |
|---|---|
| `backend` (API + runtime + engine) | Container Apps, 1 replica, `/api/health` probe |
| `agents` (Concierge, Weather, Grid, Events) | Container Apps, 1 replica, always on (Agentverse / ASI:One reachability) |
| Frontend | Static Web Apps (API, SpacetimeDB, Convex URLs as build-time env) |
| Secrets | Container Apps secrets (or Key Vault if time) |
| Monitoring | Application Insights if time: requests, escalations, Claude latency, agent messages |
| Claude | Anthropic API; Microsoft Foundry via `CLAUDE_PROVIDER=foundry` if Marketplace billing works on the student account |

## Microsoft track ask (Built for the Real World / Customer Impact)
Customer understanding, measurable usefulness, path from prototype to production, responsible design, end-to-end function.
Talk to at least one restaurant owner/manager and quote them.

## Connectivity
Demo laptop and ESP32 on a phone hotspot. Offline fallback: `LIVE_TRANSPORT=ws`, `STORE=memory`, `HARDWARE=off`, cached backtest,
recorded context. The video covers the ASI:One flow if venue internet fails.
