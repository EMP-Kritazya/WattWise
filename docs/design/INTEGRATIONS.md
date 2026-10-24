# Design: Sponsor integrations (owners: Suyog for Fetch.ai, Claude, SpacetimeDB, Convex, ESP32 · Kritazya for Azure)

How WattWise uses each sponsor tool, what each track needs from us, and how every piece falls back.
Shapes live in CONTRACTS.md (sections 5 and 6); this file covers wiring, setup and requirements.

## Map
| Tool | Job in WattWise | Code | Fallback |
|---|---|---|---|
| Fetch.ai (uAgents, Agentverse, ASI:One) | Owner's chat door; the whole owner workflow runs inside ASI:One | `agent/fetch_agent.py` | Dashboard chat drawer |
| Claude | Explains, answers, proposes; never decides or computes | `agent/` | Labeled templates |
| SpacetimeDB | Live shared kitchen every viewer subscribes to; judges' surge buttons | `spacetime/`, `runtime/spacetime_publisher.py` | `/ws` (`LIVE_TRANSPORT=ws`) |
| Convex | Durable records, proposals, backtest results, ESP32 bridge | `convex/`, `store/`, `runtime/device_bridge.py` | Memory store (`STORE=memory`), simulated hub |
| ESP32 + convex-esp32 | Real low-voltage stand-in loads switched by engine commands | `firmware/` | Simulated hub (`HARDWARE=off`) |
| Microsoft Azure | Hosting: Container Apps + Static Web Apps | `infra/` | Laptop on a phone hotspot |

## Fetch.ai: what the track requires (from the Cal Hacks 13.0 hackpack)
- [ ] At least one agent registered on **Agentverse**, categorized **Innovation Lab**.
- [ ] Implements the **Agent Chat Protocol**; discoverable and directly usable through **ASI:One**.
- [ ] Meaningful tool execution or multi-agent orchestration; primary owner workflow completes **inside ASI:One**, no custom frontend.
- [ ] Public GitHub repo with run/test instructions; README lists agent **name and address** and carries the badges
      `![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)` and `![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)`.
- [ ] 3 to 5 min demo video. Submit on Devpost **and** register through the Cal Hacks ASI:One Submission Agent.
- Bonus: multi-agent collaboration, ASI Interactive Cards, Payment Protocol with a credible model, recovery from failed
  tool calls, real-time data, an agent that could keep running after the event.
- Judging: functionality 25%, use of Fetch.ai tech 20%, innovation 20%, real-world impact 20%, UX + presentation 15%.

Owner flows that must work in ASI:One: "What will lunch cost me?" (forecast + plan) · "Approve it" / "Undo that" ·
"Never touch the walk-in after 9 PM" (proposal → confirm) · "How much did we save this month?" (engine numbers only).
Confirmation of a Proposal is matched by code (card button or `confirm`/`yes` to the latest pending item), never by the model.

## SpacetimeDB
- Module in TypeScript under `spacetime/` (tables + reducers in CONTRACTS.md section 5). Publish with the `spacetime` CLI;
  generate TS bindings into the frontend's generated folder.
- There is no Python SDK. The runtime calls reducers over HTTP: `POST /v1/database/<db>/call/<reducer>` with a JSON array of
  arguments and the runtime identity's bearer token; new surge requests are read with the SQL endpoint.
- **One batched `publish_ticks` call per real tick** for both lanes (not one call per device).
- Runtime-only reducers check the caller identity against the runtime identity stored at init.
- Track ask: SpacetimeDB must be the core of the live experience (shared state, many users writing at once), not a side cache.

## Convex
- `convex/schema.ts` + functions from CONTRACTS.md section 6. Python side: Convex Python client (`pip install convex`).
- ESP32 subscribes to `commands:forDevice(hub_id)`; Convex pushes every change over the sync socket (no polling).
- The simulated hub can call the same `devices:report` / `commands:ack` functions to test the bridge without hardware.
- Track ask: Convex is load-bearing (devices, commands, proposals, records), not a side feature.

## ESP32 hub
| Item | Plan |
|---|---|
| Library | `convex-esp32` (alpha, no guarantee of support): reactive queries, mutations, actions over one TLS WebSocket |
| Board | ESP32-S3 with PSRAM preferred (falls back to internal RAM); Arduino-ESP32 core 3.2+; ArduinoJson 7 |
| Limits | 12 subscriptions, 8 in-flight requests, one TLS session at a time; keep queries narrow, payloads small |
| Loads | 2 small 5 to 12 V fans / LED strips via MOSFET modules; INA219 for current. Nothing mains powered |
| Venue | No soldering inside the venue: breakouts with headers, breadboard, jumpers. Cal Hacks rental booth has ESP32s (bring an S3 for PSRAM) |
| Mapping | Convex `device_map`: hub_id + channel → device_id + `scale` (bench W → kitchen kW); UI says "measured (scaled)" |
| Fail safe | No Convex contact for 30 s → every load returns to normal operation. Runtime: no reading for 30 s → device back to simulated + `hub_offline` |
| Start | Bench test in Phase 2; real loads only after the Phase 3 gate passes |

## Microsoft Azure
- **Container Apps**: one image (FastAPI + run loop + uAgent). **min replicas = max replicas = 1** — lanes, run loop and
  pending approvals are in memory; scale to zero or scale out breaks the demo. Secrets as Container Apps secrets.
  `/api/health` as the probe. Logs to Application Insights if time allows.
- **Static Web Apps**: the frontend build. API base URL and SpacetimeDB/Convex URLs as build-time env.
- Track ask (Built for the Real World / Customer Impact): customer understanding, measurable usefulness, path from prototype
  to production, responsible design, end-to-end functionality. Talk to at least one restaurant owner/manager and quote them.

## Anthropic track
Named community: independent restaurant owners on a commercial tariff with demand charges. A real problem someone lived.
Works on Monday. Where Claude could go wrong and our guard: a misstated number (Claude quotes tool results only) and acting
without consent (every change is a Proposal the owner confirms).

## Connectivity
Nothing to install for users, but the system needs internet (Claude, Agentverse/ASI:One, SpacetimeDB, Convex, ESP32 WiFi).
Demo laptop and ESP32 run on a phone hotspot. Offline fallback for the Live and Proof tabs: `LIVE_TRANSPORT=ws`,
`STORE=memory`, `HARDWARE=off`, cached backtest. The video covers the ASI:One flow in case venue internet fails.
