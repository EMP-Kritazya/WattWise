# CLAUDE.md — WattWise project policy

Read this at the start of every session. If a request conflicts with this file, stop and ask before coding.
Then read your own task file, `docs/team/<YOUR_NAME>.md`: it is your personal instruction set (scope, tasks, fake data, out of scope).

## The product in 8 lines

WattWise keeps a restaurant's electricity peak under the owner's cap without stopping service.
A **simulation in the browser** (one sim host tab) models the appliances and customers. Every appliance reports to one **hub**
(an ESP32-style controller; a real ESP32 can join through Convex), which talks to **FastAPI** over a WebSocket. FastAPI owns the
clock (1 sim minute per tick, 120×) and passes the hub's current state to the **engine**, which computes every number and,
every 5 simulated minutes, returns commands that travel back through the hub to the appliances. **Fetch.ai agents** fetch live
context (weather, prices, events) on a fixed interval. When no move inside the owner's rules and preferences can hold the cap,
the engine **escalates** with 2–3 evaluated alternatives; **Claude chooses the best one within its authority itself** (the engine
validates it) so the kitchen never stops for the owner; with no choice in time, the engine's safe default applies. Every screen updates live from **SpacetimeDB**.
Proof: a year of restaurant data replayed on a real tariff.

Team: **Kritazya** (engine brain, data + proof, SpacetimeDB, Azure backend) · **Suyog** (API, runtime, Claude, Fetch.ai agents,
Convex, ESP32) · **Ashirwad** (simulation, entire frontend, Azure frontend). Sponsors: Fetch.ai (primary), Claude,
SpacetimeDB, Convex, Microsoft Azure.

## Core vocabulary (exact words in code and UI)

| Term                   | Meaning                                                                                                                                         |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **importance**         | Per device: `always_on` (never touched), `flexible` (reduced power for a while, never stops), `deferrable` (delayed, must finish by a deadline) |
| **limits**             | Owner rules per device (`min_power_pct`, `max_reduce_min`, `max_delay_min`, `must_finish_by`)                                                   |
| **peak cap**           | Owner's maximum 15-minute average power in **kW** (`peak_cap_kw`)                                                                               |
| **simulation**         | TypeScript models of appliances, physics and customers (`frontend/src/sim/`), run only in the sim host tab; steps once per `sim_tick`           |
| **hub**                | The one controller every appliance reports to and every command goes through (`frontend/src/hub/`); speaks the hub protocol on `/ws/hub`        |
| **sim host**           | The single browser tab (`/sim`) running the simulation + hub. Others are viewers                                                                |
| **tick**               | One `sim_tick` from FastAPI = 1 simulated minute; 120× = one tick every 0.5 real s. The engine replans every 5 ticks                            |
| **context**            | Structured live data from Fetch agents: weather, prices, events, crowd effect                                                                   |
| **decision**           | One engine action on one device, with a reason and an engine-computed effect                                                                    |
| **escalation**         | Engine found no way inside the owner's rules and preferences to hold the cap; it offers 1–3 evaluated alternatives                |
| **authority**          | Bounds within which Claude resolves every escalation itself (`ClaudeAuthority`; the Builder sends full authority, no UI)                        |
| **proposal**           | A change suggested by the AI, applied by code only after an owner confirmation                                                                  |
| **owner confirmation** | UI Confirm, an ASI:One card button, or a `confirm` / `yes` reply to the latest pending item (matched by code)                                   |
| **lane**               | `without` (no control) or `with` (WattWise); two kitchens side by side, same customers                                                          |
| **source**             | `simulated` or `measured` (only real ESP32 readings)                                                                                            |

## Read before coding

| File                                                                                                                                                       | When                                                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `docs/team/<you>.md`                                                                                                                                       | Every session: your branch, scope, phase tasks, checks                                  |
| `docs/PRINCIPLES.md`                                                                                                                                       | Once, then whenever in doubt                                                            |
| `docs/ARCHITECTURE.md`                                                                                                                                     | Every session                                                                           |
| `docs/CONTRACTS.md`                                                                                                                                        | Before touching any shared shape, endpoint, table, facade method, tool or agent message |
| `docs/design/ENGINE.md` · `SIMULATION.md` · `API.md` · `AGENTS.md` · `SPACETIMEDB.md` · `CONVEX_AND_ESP32.md` · `UI.md` · `DATA_AND_PROOF.md` · `AZURE.md` | When working in that area                                                               |
| `Main_Gaps.md`                                                                                                                                             | Open design points: the demo decision in force and what's still to design (Kritazya)    |
| `docs/DEMO.md`                                                                                                                                             | Demo mode, pitch, video                                                                 |

## Golden rules (non-negotiable)

1. **The engine computes every number.** kW, kWh, $, forecasts, savings, option projections. No LLM ever produces a user-facing number; the AI quotes tool results only.
2. **The engine decides routine moves; Claude only resolves escalations.** Claude picks one engine-computed option id, offered all ranked options with their authority flags; only authorized choices are accepted. Code validates it and applies it. The owner is never asked and the clock never pauses for an escalation. No answer in time → the engine's safe default.
3. **The engine never waits for AI.** The kitchen runs identically with Claude and every agent switched off (default options, last known context, template text).
4. **Owner rules are hard limits.** `always_on` never commanded; `flexible` never below `min_power_pct`; `deferrable` always finishes by `must_finish_by`; the food-safety floor (refrigeration ≥ 50 %) can never be crossed, not even by escalation.
5. **Energy is moved, never deleted.** Owed-energy ledger per flexible device, repaid the same day.
6. **Context enters as structured data.** Agents post numbers unchanged; Claude never retypes a number. Fuzzy judgments are categories (`crowd_effect`) the engine maps to numbers.
7. **The engine does no I/O.** No HTTP, SpacetimeDB, Convex or AI calls in `engine/`. Context comes in and commands go out as plain objects.
8. **No peeking.** Replay and backtest only see rows before "now".
9. **Units in names** (`_kw`, `_kwh`, `_usd`, `_min`, `_pct`, `_c`). UTC inside, local time at the edges.
10. **Deterministic.** Seeds everywhere. `DEMO_MODE=1` uses recorded context and gives the identical run every time.
11. **Honest labels.** `simulated` / `measured` / `calibrated_model` / `live_api` / `recorded`, everywhere data appears.
12. **Contracts first.** Change `docs/CONTRACTS.md` in the same commit as any shared shape; tell the team.
13. **The hub is the only door.** The engine sees appliances only as HubReports and changes them only with Commands that go back
    through the hub. The simulation never sees the engine. The hub is the truth of appliance state; the engine is the truth of every
    number. Charts draw SpacetimeDB rows; the Simulation view draws appliances only through `useDevices()` (hub state in the sim host, `live_device` elsewhere).
14. **FastAPI owns time.** The simulation steps only on `sim_tick`; no wall clock or unseeded randomness in `src/sim` / `src/hub`.

## Repo layout and owners

```
backend/
  contracts/   Pydantic models for every shared shape                                   [Kritazya, changes by PR]
  engine/      kitchen.py (facade), meter.py, forecaster.py, context.py, decider.py,     [Kritazya]
               escalation.py, rules.py, ledger.py, compare.py, replay.py  (internals TBD)
  backtest/    runner.py, policies.py, assumptions.yaml                                  [Kritazya]
  data/        loaders, distribution recipe [Kritazya] · equipment_catalog.json [Ashirwad]
  live/        spacetime_client.py: publish_ticks, publish_feed, …, read_surges          [Kritazya]
  api/         FastAPI app, routes, /ws (viewers) + /ws/hub (sim host)                   [Suyog]
  runtime/     loop.py (clock), hub_link.py, lanes.py, events.py, device_bridge.py,      [Suyog]
               escalations.py
  agent/       claude_agent.py, tools.py, prompts.py, proposals.py, templates.py         [Suyog]
  store/       Convex client + in-memory fallback (same interface)                       [Suyog]
  fakes/       fake_kitchen.py, fake_hub_client.py [Suyog] · fake_live.py [Kritazya]
  tests/       engine/ backtest/ live/ [Kritazya] · api/ runtime/ agent/ [Suyog]
agents/        Fetch uAgents: concierge (ASI:One chat), weather, grid, events            [Suyog]
spacetime/     SpacetimeDB module (TypeScript): tables + reducers                        [Kritazya]
convex/        Convex schema + functions                                                  [Suyog]
firmware/      ESP32 sketch (convex-esp32)                                                [Suyog]
frontend/      React + TS + Vite                                                          [Ashirwad]
  src/sim/     appliances, customers, two-lane kitchen (sim host only) · src/hub/ hub + /ws/hub link
  src/screens/ src/data/  every screen + live hooks (SpacetimeDB / REST / /ws) · src/mocks/ fixture-driven fakes
infra/         Azure Container Apps [Kritazya] · Static Web Apps [Ashirwad] · docker-compose
contracts/     ws_messages.schema.json · fixtures/ (shared fake data, `fixture-builder`)   [Kritazya, changes by PR]
docs/  ·  .claude/agents/  ·  data/ (gitignored)
```

Import rules: API/runtime/agent import the engine **only** via
`from engine import Kitchen, run_backtest, compare_lanes, RuleError`.
The engine imports nothing from api/, runtime/, agent/, store/, live/. In `frontend/`, screens never import `src/sim` or `src/hub`;
`src/sim` never imports screens or data hooks. The frontend imports no backend code. Every fake reads `contracts/fixtures/`.

## Branches

Work on your own branch (`kritazya`, `suyog`, `ashirwad`). Merge to `main` only at integration points, through a PR
reviewed by `architecture-reviewer`. Never edit another person's folders on your branch; ask them.

## Stack

Python 3.11, FastAPI, Pydantic v2, NumPy, pandas, pytest · Fetch.ai uAgents, Agentverse, ASI:One (Agent Chat Protocol) ·
Claude (Anthropic API; Microsoft Foundry via env switch) · SpacetimeDB (TypeScript module, HTTP reducer calls from Python,
TypeScript client in the browser) · Convex (Python client, convex-esp32) · React + TypeScript + Vite, Tailwind, shadcn/ui, Recharts ·
Azure Container Apps (exactly one replica per app) + Static Web Apps. Generated code is never hand-edited.

## How to work (Claude Code)

1. Read the docs for your task; restate the task, the files you'll touch, and the gate you're aiming at (≤ 5 lines).
2. Over ~50 lines: propose a plan and wait for approval.
3. One module per session; small diffs; run `pytest` / `npm run build` / `spacetime build` before saying done.
4. Never silently fake data. Stubs are marked `# STUB:` and listed in your summary.
5. Unclear contract → stop and ask. Never invent a shape.
6. End with: what changed, tests and results, stubs, contract changes, the task you ticked, the subagent to run next.

## Subagents (`.claude/agents/`) — at checkpoints; they share your usage limit

`architecture-reviewer` (before every merge) · `contract-sync` (any shared shape change) · `engine-test-author` (before each engine module: hand-computed failing tests) · `engine-math-verifier` (engine or simulation change) ·
`backtest-auditor` (before any savings number is shown) · `fetch-compliance` (before submission) · `demo-readiness` (from feature freeze) ·
`fixture-builder` (Phase 1, and after every `contract-sync`: regenerates `contracts/fixtures/`).

## Never

Let an LLM produce a user-facing number · let Claude act outside its authority · cross the food-safety floor ·
let replay read future rows · touch an always_on device · put network calls in `engine/` · commit secrets or datasets ·
refactor across workstreams after feature freeze.
