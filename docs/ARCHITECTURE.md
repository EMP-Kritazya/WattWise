# Architecture

## The system
```
 OWNER (phone)                          OWNER + JUDGES (browsers)
 ASI:One chat                           React dashboard  ── Azure Static Web Apps          [Ashirwad]
     │ Agent Chat Protocol                  │ REST: config, clicks,          ▲ live subscription (every viewer, same kitchen)
     ▼                                      │ approvals, chat, authority     │ + judges' surge buttons (request reducer)
 ┌──────────── FETCH AGENTS (Agentverse) ───┼─────────┐                      │
 │ Concierge (chat, Claude) · Weather ·     │         │                      │
 │ Grid prices · Events          [Suyog]    │         │                      │
 └───────┬───────────────────────────────── │ ────────┘                      │
         │ REST (context, chat relay)       ▼                                │
 ┌───────▼──────── BACKEND · Azure Container Apps, 1 replica ─────────────┐  │
 │ API (FastAPI)  ·  RUNTIME (loop, two lanes, escalations, device bridge)│  │   [Suyog]
 │ AGENT (Claude: explain, answer, propose, resolve escalations)          │  │
 │      │ engine facade (Python calls, plain objects)                     │  │
 │ ┌────▼──────────────── ENGINE (no I/O) ─────────────────────────────┐ │  │
 │ │ SIMULATION: devices → HUB ⇄ commands            [Ashirwad]        │ │  │
 │ │ BRAIN: meter → forecaster(+context) → decider → escalation        │ │  │   [Kritazya]
 │ │        → executor → hub ;  ledger · compare_lanes · replay/backtest│ │  │
 │ └────────────────────────────────────────────────────────────────────┘ │  │
 │ LIVE client ── HTTP reducers ──────────────────────────────────────────┼──┘──▶ SpacetimeDB (live)   [Kritazya]
 │ STORE + DEVICE BRIDGE ─────────────────────────────────────────────────┼─────▶ Convex (records, devices) [Suyog]
 └─────────────────────────────────────────────────────────────────────────┘          ▲ convex-esp32
                                                                                ESP32 hub (optional, replaces the simulated hub)
```

## Who owns what
| Part | Owner | Builds | Never does |
|---|---|---|---|
| Engine brain + proof | Kritazya | Facade, meter, forecaster, context use, decider, escalation options, executor, rules, ledger, `compare_lanes`, replay, backtest, data, contracts models | Network, users, Claude |
| Live layer | Kritazya | SpacetimeDB module + `backend/live/` client | Business logic in reducers |
| Simulation | Ashirwad | Devices, power models, hub, customers, equipment catalog | Network, decisions |
| Frontend | Ashirwad | Every screen, data hooks (SpacetimeDB + REST + `/ws` fallback), mocks, chat drawer | Any calculation |
| API + runtime + AI | Suyog | FastAPI, run loop, lanes, escalation relay, proposals, Claude agent + tools, `/ws` fallback, FakeKitchen | Compute numbers |
| Fetch agents | Suyog | Concierge (ASI:One), Weather, Grid, Events agents | Compute numbers, retype numbers |
| Convex + ESP32 | Suyog | Records, device bridge, firmware | Decide |
| Azure | Kritazya (Container Apps) · Ashirwad (Static Web Apps) | Deploy, secrets, health probe | |

Quick test: **computes a number → engine. Simulated device behaviour → simulation. Moves data or talks to a person, AI or agent → Suyog.
Visible on screen → Ashirwad. Live tables → Kritazya.**

## Seams
| # | Seam | Form | Fake for independent work |
|---|---|---|---|
| S1 | Frontend ↔ API | REST (+ `/ws` fallback) | `frontend/src/mocks` (Ashirwad) |
| S2 | API/runtime ↔ Engine | Python facade, plain objects | `fakes/fake_kitchen.py` (Suyog) |
| S3 | Runtime → SpacetimeDB → browsers | `backend/live` client + tables/reducers + generated TS bindings | `fakes/fake_live.py` + seed script (Kritazya) |
| S4 | Runtime ↔ Convex ↔ ESP32 | Convex functions | `STORE=memory`, `HARDWARE=off` (Suyog) |
| S5 | Agents ↔ API and agent ↔ agent | REST + Fetch message models + Chat Protocol | `--recorded` mode per agent (Suyog) |
| S6 | Simulation ↔ Brain (inside engine) | Hub interface: `report()` / `deliver(command)` | `engine/fake_hub.py` (Ashirwad) |

## Four flows
**1. Tick (reflexes).** Runtime collects surges (REST + SpacetimeDB requests), draws one set of customer events, passes the
latest context and any fresh ESP32 readings, calls `step(1)` on both lanes → hub reports → meter → every 5 sim min forecast + decide
inside rules → executor commands the hub → runtime gets `TickState` (+ `new_commands`, `new_escalations`) → `compare_lanes` →
live client publishes one batch to SpacetimeDB → bridge forwards ESP32-mapped commands to Convex → store buffers records.

**2. Context (senses).** Every 10 real minutes (and on kitchen build) the Concierge asks the Weather, Grid and Events agents →
they call their APIs → structured replies → `POST /api/context` unchanged → runtime `set_context` on both lanes → forecaster uses it.
Claude classifies events into a `crowd_effect` category → `POST /api/context/crowd-effect`. Every agent message is logged → SpacetimeDB `live_agent_log`.

**3. Escalation (judgment).** Decider finds a block over the cap with no in-rules fix → builds an Escalation with 2–4 options
(each with engine-computed peak, cost, comfort impact, rule breaks, `within_authority`) and a safe default → runtime asks Claude
(context + owner preferences + options) → Claude returns an option id → runtime calls `resolve_escalation(id, option, "claude", rationale)`
→ engine validates: inside authority → applies; outside → becomes an owner Proposal. Deadline passes with no answer → default applies.
Demo mode pauses the clock while waiting.

**4. Owner (control).** Dashboard REST or ASI:One chat → explanations and answers from engine tools → any change is a Proposal →
owner confirms → code applies via the facade.

## Hub swap (simulated ESP32 → real ESP32)
The brain only talks to the hub interface. Simulated hub: in-process. Real hub: runtime forwards the `with` lane's commands for
mapped devices to Convex (`HARDWARE=esp32`), the ESP32 executes them and reports readings, which enter via `ingest_reading()`.
Bridge test without hardware: `HARDWARE=sim_bridge` sends the simulated hub's readings and commands through the same Convex
functions, so the real ESP32 is a drop-in. Every device's 15-min average is stored in Convex `device_blocks` whatever the source.

## Time
The engine has no clock; the runtime calls `step(minutes)`. 120× live, max speed in backtest, paused while an approval or escalation
waits in demo mode. Escalation deadlines are in sim time; Claude's timeout is in real time.

## Deploy
Azure Container Apps: `backend` (API + runtime + engine, min = max = 1 replica) and `agents` (uAgents, 1 replica, always on).
Static Web Apps: frontend. SpacetimeDB and Convex: their hosted clouds. Claude: Anthropic API, or Microsoft Foundry via env.

## Out of scope
Mains-powered equipment, real restaurant installs, multiple kitchens per deployment.
