# CLAUDE.md — WattWise project policy

Read this at the start of every session. If a request conflicts with this file, stop and ask before coding.

## The product in 5 lines
WattWise keeps a restaurant's electricity peak under control without stopping service.
Every appliance reports its power to one hub box (a simulated ESP32; optionally a real ESP32 through Convex). The **engine**
reads the hub, forecasts the next 2 hours, decides which appliances to delay or turn down, and executes inside the owner's rules.
The **AI** (Claude, reached in ASI:One through a Fetch.ai agent or in the dashboard chat) explains, answers and proposes;
it never makes decisions and applies a change only after the owner confirms.
We prove savings by replaying historical restaurant data with and without WattWise.

Team: **Kritazya Upreti** (engine brain, data + proof, Azure) · **Suyog** (API + AI, Fetch.ai agent, SpacetimeDB, Convex,
ESP32, frontend data layer + chat) · **Ashirwad** (simulation, frontend screens). Task lists per person: `docs/TASKS.md`. Event: Cal Hacks 13.0. Sponsor stack: Fetch.ai, Claude, SpacetimeDB, Convex (+ ESP32), Microsoft Azure.

## Core vocabulary (use these exact words in code and UI)
| Term | Meaning |
|---|---|
| **importance** | Owner-chosen class per device: `always_on`, `flexible`, `deferrable` |
| `always_on` | Never touched by the engine (fryer during service, freezer, lights) |
| `flexible` | Can run at reduced power for a while but never stops (HVAC, walk-in cooler) |
| `deferrable` | Can be delayed, must finish by a deadline (dishwasher, ice machine batch) |
| **peak cap** | Owner's maximum power target in **kW** (`peak_cap_kw`). Power is kW; energy is kWh. |
| **hub** | The single box every device reports to (simulated ESP32; optionally a real ESP32 via Convex). |
| **source** | Where a reading came from: `simulated` (engine model) or `measured` (real ESP32 sensor). |
| **owner confirmation** | An explicit owner tap: UI Confirm button, ASI:One card, or a `confirm` reply to the latest pending item. The only thing that lets an AI proposal be applied. |
| **proposal** | A change suggested by the AI (importance, peak cap, approve/undo, customer event) waiting for owner confirmation. |
| **decision** | One engine action on one device, with a reason and an effect. |
| **lane** | `without` (no control) or `with` (WattWise) — two kitchens run side by side in the demo. |

## Read before coding
| File | When |
|---|---|
| `docs/ARCHITECTURE.md` | Every session |
| `docs/CONTRACTS.md` | Before touching any shared shape, endpoint, message, facade method or AI tool |
| `docs/design/SIMULATION.md` | Devices, hub, clock, kitchen config, customer flow |
| `docs/design/ENGINE.md` | Meter, forecast, decision logic, execution |
| `docs/design/API.md` | Server, run loop, WebSocket, AI agent |
| `docs/design/UI.md` | Any frontend work |
| `docs/design/DATA_AND_PROOF.md` | Historical data, tariff, backtest |
| `docs/design/INTEGRATIONS.md` | Fetch.ai agent, SpacetimeDB, Convex, ESP32 bridge, Azure deploy |
| `docs/DEMO.md` | Demo mode, table pitch, video |
| `docs/CLAUDE_CODE_PHASES.md` | Session starter prompt and the block for your phase |
| `docs/TASKS.md` | Pick your task; tick it when done and tested |
| `docs/DECISIONS.md` | Before reversing any design choice |

## Golden rules (non-negotiable)
1. **The engine decides and executes. The AI never decides.** The AI only explains, answers and proposes. A proposal is
   applied by code, never by the model, and only after an owner confirmation. The engine must work with the AI switched off.
2. **The AI never computes numbers.** Every kW, kWh and $ shown to a user comes from the engine. The AI quotes tool results only.
3. **Always-on devices are never touched.** Flexible devices never go below their minimum power. Deferrable devices always finish by their deadline.
4. **Energy is conserved.** Delaying or turning down moves energy in time; it never deletes it (flexible devices catch up later).
5. **No peeking.** In replay/backtest, the engine only sees data with timestamps before "now".
6. **Units in names:** `_kw`, `_kwh`, `_usd`, `_min`, `_pct`. Timezone-aware timestamps (UTC inside, local time at the edges).
7. **Deterministic.** Anything random takes a seed. `DEMO_MODE=1` gives the identical run every time.
8. **Simulated is labeled.** Nothing simulated is presented as measured. Only real ESP32 sensor readings are `measured`.
9. **Contracts are shared.** Change `docs/CONTRACTS.md` in the same commit as any shape change, and tell the team.
10. **The engine does no I/O.** No HTTP, database, Convex, SpacetimeDB or AI calls inside `engine/`. Network code lives in
   `runtime/`, `store/` and `agent/`; the engine receives readings and returns commands as plain objects.

## Repo layout and owners
```
backend/
  contracts/   Pydantic models for every shared shape                         [Kritazya, changes by PR]
  engine/      kitchen.py (facade), meter.py, forecaster.py, decider.py,       [Kritazya]
               rules.py, replay.py, compare_lanes
               devices.py, hub.py, customers.py (simulation)                   [Ashirwad]
  backtest/    runner.py, policies.py, assumptions.yaml                         [Kritazya]
  data/        loaders, distribution recipe                                     [Kritazya]
               equipment_catalog.json                                           [Ashirwad]
  api/         FastAPI app, routes, websocket (fallback live transport)         [Suyog]
  runtime/     run loop (clock driver), lanes, event source,                    [Suyog]
               spacetime_publisher.py, device_bridge.py
  agent/       Claude agent, tools, prompts, fallback templates, proposals,     [Suyog]
               fetch_agent.py (Fetch.ai uAgent, Agent Chat Protocol)
  store/       Convex + in-memory fallback (same interface)                     [Suyog]
  fakes/       fake_kitchen.py (stand-in engine until the Phase 2 gate)         [Suyog]
  tests/       engine/ [Kritazya] · simulation/ [Ashirwad] · api/ [Suyog]
frontend/      React + TS + Vite app
  src/data/, src/mocks/, src/types/ (generated), src/features/chat/              [Suyog]
  src/features/builder/, live/, feed/, proof/, src/components/                   [Ashirwad]
spacetime/     SpacetimeDB module (TypeScript): live tables + reducers          [Suyog]
convex/        Convex schema + functions (records, proposals, ESP32 bridge)     [Suyog]
firmware/      ESP32 sketch using convex-esp32                                  [Suyog]
infra/         Azure Container Apps + Static Web Apps config                    [Kritazya]
contracts/     ws_messages.schema.json (shared WebSocket message schema)
docs/          this documentation
.claude/agents/ project subagents (committed; only .claude/settings.local.json is ignored)
data/          downloaded datasets (gitignored)
```
Simulation files live inside `engine/`, so every engine rule (no I/O, determinism, units, `engine-math-verifier`) applies to them.
Import rule: API code imports the engine **only** through
`from engine import Kitchen, CustomerSource, run_backtest, compare_lanes, RuleError`.
The engine imports nothing from api/, runtime/, agent/, store/.

## Stack
Python 3.11, FastAPI, Pydantic v2, NumPy, pandas, pytest · React + TypeScript + Vite, Tailwind, shadcn/ui, Recharts ·
SpacetimeDB (live shared kitchen; FastAPI WebSocket as fallback) · Convex (durable records + ESP32 bridge; in-memory fallback) ·
Fetch.ai uAgents + Agentverse + ASI:One (owner chat) · Claude API with tool use (model from env `ANTHROPIC_MODEL`) ·
Microsoft Azure (Container Apps, exactly one replica; Static Web Apps) · ESP32 + convex-esp32 (optional hardware).
Frontend types are generated (OpenAPI + `contracts/ws_messages.schema.json` + SpacetimeDB bindings + Convex types), never hand-written.

## How to work (Claude Code)
1. Read the docs listed above for your task. Restate the task and the files you'll touch.
2. Over ~50 lines: propose a plan and wait for approval.
3. One module per session; small diffs; run tests (`pytest`, `npm run build`) before saying done.
4. Never silently fake data. Stubs are marked `# STUB:` and listed in your summary.
5. Unclear contract → stop and ask. Don't invent one.
6. Finish by ticking the task in `docs/TASKS.md` and summarising changes + stubs.

## Subagents (`.claude/agents/`) — run at checkpoints, they share your usage limit
| Subagent | When |
|---|---|
| `architecture-reviewer` | Before merging to main; at every gate |
| `contract-sync` | Whenever a shared shape changes |
| `engine-math-verifier` | After any engine change |
| `backtest-auditor` | Before any savings number is shown |
| `demo-readiness` | From feature freeze (Phase 5) and before rehearsals |

## Definition of done
Tests pass (including a hand-computed case) · matches CONTRACTS.md · works in `DEMO_MODE=1` · no unlabeled simulated data ·
the owner can explain every line.

## Never
Compute user-facing numbers in an LLM · let replay read future rows · touch an always_on device · commit secrets or full datasets ·
let an AI proposal apply without owner confirmation · put network calls in `engine/` · refactor across workstreams after feature freeze.
