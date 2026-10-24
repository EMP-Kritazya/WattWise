# CLAUDE.md — WattWise project policy

Read this at the start of every session. If a request conflicts with this file, stop and ask before coding.
Then read your own task file: `docs/team/<YOUR_NAME>.md`.

## The product in 6 lines

WattWise keeps a restaurant's electricity peak under the owner's cap without stopping service.
Every appliance reports to one **hub** (a simulated ESP32; a real ESP32 can replace it through Convex).
**Fetch.ai agents** bring live context (weather, grid prices, nearby events). The **engine** computes every number and,
every 5 simulated minutes, moves flexible appliances inside the owner's rules. When no in-rules move can hold the cap, the
engine **escalates**: it computes 2–4 options and **Claude chooses one** using the context and the owner's preferences,
within an authority limit the owner set. Beyond that limit, the owner confirms. Proof: a year of restaurant data replayed on a real tariff.

Team: **Kritazya** (engine brain, data + proof, SpacetimeDB, Azure backend) · **Suyog** (API, runtime, Claude, Fetch.ai agents,
Convex, ESP32) · **Ashirwad** (simulation, entire frontend, Azure frontend). Sponsors: Fetch.ai (primary), Claude,
SpacetimeDB, Convex, Microsoft Azure.

## Core vocabulary (exact words in code and UI)

| Term                   | Meaning                                                                                                                                         |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **importance**         | Per device: `always_on` (never touched), `flexible` (reduced power for a while, never stops), `deferrable` (delayed, must finish by a deadline) |
| **limits**             | Owner rules per device (`min_power_pct`, `max_reduce_min`, `max_delay_min`, `must_finish_by`)                                                   |
| **peak cap**           | Owner's maximum 15-minute average power in **kW** (`peak_cap_kw`)                                                                               |
| **hub**                | The one box every device reports to. `simulated` by default; a real ESP32 via Convex when `HARDWARE=esp32`                                      |
| **context**            | Structured live data from Fetch agents: weather, prices, events, crowd effect                                                                   |
| **decision**           | One engine action on one device, with a reason and an engine-computed effect                                                                    |
| **escalation**         | Engine found no in-rules way to hold the cap; it offers options with computed numbers                                                           |
| **authority**          | Owner-set bounds within which Claude may resolve an escalation without asking (`ClaudeAuthority`)                                               |
| **proposal**           | A change suggested by the AI, applied by code only after an owner confirmation                                                                  |
| **owner confirmation** | UI Confirm, an ASI:One card button, or a `confirm` / `yes` reply to the latest pending item (matched by code)                                   |
| **lane**               | `without` (no control) or `with` (WattWise); two kitchens side by side, same customers                                                          |
| **source**             | `simulated` or `measured` (only real ESP32 readings)                                                                                            |

## Read before coding

| File                                                                                                                                                       | When                                                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `docs/team/<you>.md`                                                                                                                                       | Every session: your branch, scope, phase tasks, gates                                   |
| `docs/PRINCIPLES.md`                                                                                                                                       | Once, then whenever in doubt                                                            |
| `docs/ARCHITECTURE.md`                                                                                                                                     | Every session                                                                           |
| `docs/CONTRACTS.md`                                                                                                                                        | Before touching any shared shape, endpoint, table, facade method, tool or agent message |
| `docs/design/ENGINE.md` · `SIMULATION.md` · `API.md` · `AGENTS.md` · `SPACETIMEDB.md` · `CONVEX_AND_ESP32.md` · `UI.md` · `DATA_AND_PROOF.md` · `AZURE.md` | When working in that area                                                               |
| `docs/TIMELINE.md`                                                                                                                                         | Phases, clock times, gates, merge order                                                 |
| `docs/DECISIONS.md`                                                                                                                                        | Before reversing any design choice                                                      |
| `docs/DEMO.md`                                                                                                                                             | Demo mode, pitch, video                                                                 |

## Golden rules (non-negotiable)

1. **The engine computes every number.** kW, kWh, $, forecasts, savings, option projections. No LLM ever produces a user-facing number; the AI quotes tool results only.
2. **The engine decides routine moves; Claude only resolves escalations.** Claude picks one engine-computed option id. Code validates it against the owner's authority and applies it. Outside the authority → owner confirmation. No answer in time → the engine's safe default.
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

## Repo layout and owners

```
backend/
  contracts/   Pydantic models for every shared shape                                   [Kritazya, changes by PR]
  engine/      kitchen.py (facade), meter.py, forecaster.py, context.py, decider.py,     [Kritazya]
               escalation.py, rules.py, ledger.py, compare.py, replay.py
               devices.py, hub.py, customers.py  (simulation)                            [Ashirwad]
  backtest/    runner.py, policies.py, assumptions.yaml                                  [Kritazya]
  data/        loaders, distribution recipe [Kritazya] · equipment_catalog.json [Ashirwad]
  live/        spacetime_client.py: publish_ticks, publish_feed, …, read_surges          [Kritazya]
  api/         FastAPI app, routes, /ws fallback                                         [Suyog]
  runtime/     loop.py, lanes.py, events.py, device_bridge.py, escalations.py            [Suyog]
  agent/       claude_agent.py, tools.py, prompts.py, proposals.py, templates.py         [Suyog]
  store/       Convex client + in-memory fallback (same interface)                       [Suyog]
  fakes/       fake_kitchen.py [Suyog] · fake_live.py [Kritazya]
  tests/       engine/ backtest/ live/ [Kritazya] · simulation/ [Ashirwad] · api/ runtime/ agent/ [Suyog]
agents/        Fetch uAgents: concierge (ASI:One chat), weather, grid, events            [Suyog]
spacetime/     SpacetimeDB module (TypeScript): tables + reducers                        [Kritazya]
convex/        Convex schema + functions                                                  [Suyog]
firmware/      ESP32 sketch (convex-esp32)                                                [Suyog]
frontend/      React + TS + Vite: all screens, data hooks, mocks, chat drawer            [Ashirwad]
infra/         Azure Container Apps [Kritazya] · Static Web Apps [Ashirwad] · docker-compose
contracts/     ws_messages.schema.json
docs/  ·  .claude/agents/  ·  data/ (gitignored)
```

Import rules: API/runtime/agent import the engine **only** via
`from engine import Kitchen, CustomerSource, run_backtest, compare_lanes, RuleError`.
The engine imports nothing from api/, runtime/, agent/, store/, live/. Simulation files inside `engine/` follow every engine rule.

## Branches

Work on your own branch (`kritazya`, `suyog`, `ashirwad`). Merge to `main` only at gates (`docs/TIMELINE.md`) through a PR
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

`architecture-reviewer` (before every merge) · `contract-sync` (any shared shape change) · `engine-math-verifier` (engine or simulation change) ·
`backtest-auditor` (before any savings number is shown) · `fetch-compliance` (before submission) · `demo-readiness` (from feature freeze).

## Never

Let an LLM produce a user-facing number · let Claude act outside the owner's authority without confirmation · cross the food-safety floor ·
let replay read future rows · touch an always_on device · put network calls in `engine/` · commit secrets or datasets ·
refactor across workstreams after feature freeze.
