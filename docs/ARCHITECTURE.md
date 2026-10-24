# Architecture

## The whole system
```
 ┌──────────────────────────── FRONTEND (teammate) ────────────────────────────┐
 │  Kitchen Builder  ·  Live Simulation (interactive kitchen, two lanes)        │
 │  Proof  ·  Chat drawer                                                       │
 └───────────────────────────────┬──────────────────────────────────────────────┘
                                 │  Seam 1: REST + WebSocket (JSON)
 ┌───────────────────────────────┴──── API + AI (teammate) ─────────────────────┐
 │  FastAPI server · run loop (moves time) · WebSocket · AI agent (Claude)       │
 │  · store (Tiger Data)                                                         │
 └───────────────────────────────┬──────────────────────────────────────────────┘
                                 │  Seam 2: engine facade (Python calls)
 ┌───────────────────────────────┴──── ENGINE (Kritazya) ───────────────────────┐
 │  SIMULATION: devices ──report power──▶ HUB (simulated ESP32)                 │
 │                                          │ restaurant state                   │
 │  BRAIN:      meter → forecaster → decider → executor ──commands──▶ hub ──▶ devices │
 │  PROOF:      replay + backtest (historical data, real tariff)                │
 └───────────────────────────────────────────────────────────────────────────────┘
```

## Who owns what
| Part | Owner | Builds | Never does |
|---|---|---|---|
| Frontend | teammate | Kitchen Builder (equipment, counts, importance, peak cap), interactive Live Simulation view, Proof page, chat drawer, mock server | Any calculation |
| API + AI | teammate | Server, endpoints, WebSocket, run loop (calls `step()`), approvals relay, Claude agent + tools, store, `FakeKitchen` | Decide or compute numbers |
| Engine | Kritazya | Simulated devices + hub, meter, forecaster, decider, executor, rules, replay, backtest, data loading | Talk to users or to Claude |

Simple test for any new task: **computes a number → engine. Moves data or talks to a person/AI → API. Visible on screen → frontend.**

## How it works, one tick
1. The run loop (API) calls `kitchen.step(1)` for both lanes with the same customer events.
2. Each simulated device updates its power and reports to the **hub**.
3. The hub sums the restaurant's state (total kW, per-device kW, states).
4. The meter updates energy, the 15-minute demand average, the month peak and cost.
5. Every 5 simulated minutes the **brain** runs: forecast → decide → execute inside rules
   (outside rules → decision marked `awaiting_approval`).
6. The API pushes the tick to the UI, sends approval requests to the owner, and asks the AI to explain notable decisions.

## The two seams
- **Seam 1 (Frontend ↔ API):** JSON over REST + WebSocket. Frontend builds against a mock server until the API is ready.
- **Seam 2 (API ↔ Engine):** Python function calls with Pydantic objects (same shapes as the JSON). API builds against
  `FakeKitchen` until the engine is ready; switch with `KITCHEN_IMPL=real`.

## Where the AI sits
Outside the decision loop. It reads engine state through tools, explains decisions, answers questions, and turns
owner requests ("never touch the fryer") into settings changes **that the owner confirms**. If the AI is down,
the kitchen runs exactly the same; explanations fall back to templates (labeled).

## Time
The engine has no clock. It only moves when `step(minutes)` is called. The run loop decides speed:
120× in the live demo, as fast as possible in backtest, paused while an approval is pending in demo mode.

## Out of scope
A physical ESP32. The hub is simulated with the same interface a real one would use, so it could be swapped in later.
