# SUYOG.md — your working instructions (Backend: API + runtime + Claude + Fetch.ai agents + Convex + ESP32)

> **Claude Code: this file is Suyog's instruction set.** Read it first in every session, together with the golden rules in
> `CLAUDE.md`. When this file and a general doc disagree about *what Suyog builds or may touch*, this file wins.
> Anything about shared shapes is decided by `docs/CONTRACTS.md`; never change it from here.

**Branch:** `suyog` (create it from `architecture-separation` if it doesn't exist) · **Mission:** everything moves: time,
messages, agents, decisions to people.

## 1. Your job in one paragraph
You build the backend around the engine. **FastAPI** serves the UI (REST + viewer `/ws`) and the browser hub (`/ws/hub`).
The **runtime** owns the clock: every tick (1 sim minute, 0.5 real s at 120×) it sends a `sim_tick` to the hub, waits for the
`hub_report`, calls the engine for both lanes, queues the engine's Commands for the next tick, and publishes results.
**Claude** is the high-level decision maker only when the engine escalates: it picks one of the engine's evaluated options
and the engine validates it against the owner's authority. **Fetch.ai agents** fetch context (weather, prices, events)
periodically, and the Concierge is the owner's chat door in ASI:One. **Convex** stores records and bridges a real ESP32.

## 2. Scope — exactly what you may edit
| You may create and edit | Never edit (read only) |
|---|---|
| `backend/api/`, `backend/runtime/`, `backend/agent/`, `backend/store/` | `docs/` (all docs, including this file), `CLAUDE.md`, `README.md` (send agent addresses to Kritazya) |
| `backend/fakes/fake_kitchen.py`, `backend/fakes/fake_hub_client.py` | `contracts/` (shapes, schema, **fixtures**), `backend/contracts/` |
| `backend/tests/{api,runtime,agent}/` | `backend/engine/`, `backend/backtest/`, `backend/data/`, `backend/live/`, `backend/fakes/fake_live.py` |
| `agents/`, `convex/`, `firmware/` | `frontend/`, `spacetime/`, `infra/` |

## 3. Rules for this phase (independent development)
1. **Build only against the fake data** in `contracts/fixtures/` (section 5) for everything you don't own: the engine
   (`FakeKitchen`), the browser hub (`fake_hub_client.py`), and SpacetimeDB (a recording double, section 5). Your own services
   (Claude API, Fetch agents, Convex) may be real in development, but every test must pass with them off or recorded.
2. **Do not merge** anything, open PRs to `main`, or pull teammates' branches into yours. Commit to `suyog` only.
3. **Do not change any structure you don't own**: no edits to contracts, fixtures, docs, folder layout or other people's code.
   If a shape looks wrong or missing, stop, keep the code matching the contract as written, and add it to a
   "Contract questions" list in your session summary for Kritazya.
4. **Never hand-edit fixtures.** Load them; if you need a different scenario, ask Kritazya to regenerate.
5. **Compute no user-facing number.** Every kW, kWh, $ and forecast comes from the engine (FakeKitchen now). Claude quotes only
   tool results; it changes state only through `choose_escalation_option` (an offered id) and `set_crowd_effect` (a category).
6. **Import the engine only via** `from engine import Kitchen, run_backtest, compare_lanes, RuleError`, switched by
   `KITCHEN_IMPL=fake|real` (`fake` until Kritazya delivers). The engine never does I/O; you do all of it.

## 4. What to build (in order; tick when done and tested)
**A. Skeleton on fakes**
- [ ] FastAPI app with every REST endpoint (CONTRACTS.md §2), viewer `/ws`, `/api/health`, OpenAPI; Pydantic request/response models in your folder mirroring the contract (marked `# STUB: replace with backend/contracts`)
- [ ] `fakes/fake_kitchen.py`: every facade call from `fixtures/facade/` (`step` looked up by `hub_report.lane` + `tick_id` in `step_stream.jsonl`; RuleError examples raise)
- [ ] `fakes/fake_hub_client.py`: connects to `/ws/hub`, sends `hub_hello`, answers each `sim_tick` with the matching `hub_report` line (by `tick_id`) from `hub_to_server.jsonl`; `HUB_IMPL=fake`
- [ ] Store interface + memory backend (`STORE=memory`), seeded from `fixtures/convex/tables/`

**B. Clock + run loop** — design: `docs/design/API.md`
- [ ] `runtime/hub_link.py`: one sim host only (`host_taken` for the second), `sim_build` on kitchen build, `sim_tick` / `hub_report` handshake, `hub_waiting` (2 s) and `sim_host_offline` pauses, reconnect re-sends `sim_build`
- [ ] `runtime/loop.py`: 1 sim min per tick, speeds 1× / 30× / 120× / 600×, surges (REST + SpacetimeDB requests) into the next `sim_tick`, physical inputs from context, `step(1, hub_report)` per lane, engine Commands + owner commands queued for tick *n + 1*, `compare_lanes`, live publish, store buffer
- [ ] Viewer `/ws` messages and `LIVE_TRANSPORT=ws` fallback (everything over `/ws`)

**C. Claude** — design: `docs/design/API.md` (Escalations, AI agent), `docs/design/AGENTS.md` (Claude)
- [ ] `agent/tools.py` (CONTRACTS.md §4) as thin wrappers over the facade; `agent/templates.py` fallbacks; chat streaming (`chat_delta`, `chat_done`)
- [ ] `runtime/escalations.py`: send open escalations to Claude with options + context + preferences + authority; enum-constrained `choose_escalation_option`; `resolve_escalation(..., "claude", rationale)`; Proposal when `awaiting_owner`; 8 s timeout → leave for the engine's default; demo mode pauses the clock
- [ ] Proposals + owner confirmation (UI Confirm, ASI:One button, `confirm` / `yes` matched by code)
- [ ] Clock slowdown while an escalation is open (`slowed_reason`, `ESCALATION_SPEED`) — **build last; Kritazya may drop it**

**D. Fetch.ai** — design: `docs/design/AGENTS.md`
- [ ] Weather + Grid agents (live + `--recorded`), Events (tier 2); Concierge periodic context loop every `CONTEXT_INTERVAL_S` (600 s) → `POST /api/context` unchanged; agent log → `POST /api/agent-log`
- [ ] Concierge: Agent Chat Protocol, discoverable in ASI:One, real tool execution through the API, every owner flow in AGENTS.md completes inside ASI:One, Agentverse registration (Innovation Lab), agent names + addresses sent to Kritazya for README; run `fetch-compliance`

**E. Convex + ESP32** — design: `docs/design/CONVEX_AND_ESP32.md`
- [ ] Convex schema + functions (CONTRACTS.md §6), batched writes, `STORE=convex|memory`, `store_down` fallback
- [ ] Device bridge: `HARDWARE=off` (default) → `sim_bridge` → `esp32`; readings → `ingest_reading`; `hub_offline` after 30 s
- [ ] Firmware: subscribe, execute, ack, 30 s fail safe; INA219 "measured (scaled)"

## 5. Your fake data (all in `contracts/fixtures/`, read only)
| You need | Use this | How |
|---|---|---|
| The engine | `facade/*.json` (`{call, args, returns}` / `raises`), `facade/step_stream.jsonl` (240 lines: tick × lane) | `FakeKitchen` returns these exactly |
| The browser hub | `hub_protocol/hub_to_server.jsonl` (hub_hello + 120 hub_reports), single-message files | `fake_hub_client.py` replays by `tick_id` |
| What you must send the hub | `hub_protocol/server_to_hub.jsonl`, `sim_build.json`, `sim_tick.json`, `sim_control.json`, `hub_welcome_*.json` | Test that your `sim_tick` stream equals this for the scenario (commands at *n + 1*, surge at tick 31) |
| SpacetimeDB (Kritazya's live client) | `spacetime/reducers/*.json` (exact reducer args), `spacetime/rows_stream.jsonl` | Until the real client exists, call a recording double in your tests and assert payloads equal these; run dev with `LIVE_TRANSPORT=ws` |
| REST + `/ws` | `rest/*.json` (incl. 404 / 422), `ws/*.json`, `ws/stream.jsonl` | API tests compare responses and the message stream |
| Claude tools | `ai_tools/*.json` (`{tool, input, output}`, `input_enum`), `shapes/escalation_*.json` (open, resolved, awaiting_owner, expired_default) | Tool tests; escalation flow tests with Claude mocked |
| Fetch agents | `agents/*_request.json`, `*_response.json`, `context_post.json`, `agent_log.jsonl` | `--recorded` mode and context-loop tests |
| Convex | `convex/tables/*.json`, `convex/functions/*.json` | Memory store seed, function tests |
| The scenario | `scenario/demo_cafe/scenario.json`, `index.json`, `README.md`, `GAPS.md` | Escalation `e_0001` at tick 60, Claude's choice `extend_delay_dishwasher`, delivered tick 62 |

## 6. Big-picture docs (read, don't edit)
`docs/ARCHITECTURE.md` · `docs/CONTRACTS.md` §2 REST + `/ws`, §3 facade, §4 AI tools, §6 Convex, §7 agent messages, §8 hub
protocol · `docs/design/API.md` · `docs/design/AGENTS.md` · `docs/design/CONVEX_AND_ESP32.md` · `docs/PRINCIPLES.md` · `docs/DEMO.md`.
The engine and SpacetimeDB are black boxes behind the fixtures; don't build or guess their internals.

## 7. Checks before you say "done"
`pytest backend/tests/{api,runtime,agent}` passes with `KITCHEN_IMPL=fake`, `HUB_IMPL=fake`, `STORE=memory`, `HARDWARE=off`, no
Claude key and recorded agents · the scenario run produces the fixture `sim_tick` stream and reducer payloads exactly · the loop
never blocks on Claude, agents, Convex or SpacetimeDB · every external dependency has a fallback and a warning · Claude changes
state only through the two bounded tools · every agent message logged · ASI:One owner flow works end to end.

## 8. Out of scope — do not do these
Engine logic, forecasts, decisions or any cost math · editing `backend/live/` or the SpacetimeDB module (call through the documented
interface or the recording double) · frontend code · changing a contract shape or a fixture · merging or rebasing with other branches ·
restructuring folders outside your scope.

## 9. Session starter (paste into Claude Code)
```
ROLE = suyog. Read docs/team/SUYOG.md first (it is my instruction set), then CLAUDE.md golden rules, and only the docs it lists
for today's task. Build only inside my scope, only against contracts/fixtures/ for anything I don't own. Do not merge, do not edit
contracts, fixtures, docs or other folders. Task: <task>. Restate it in ≤5 lines with the files you'll touch and the fixtures
you'll use; plan first if >50 lines. End with: what changed, tests run, stubs, contract questions.
```
