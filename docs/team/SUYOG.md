# Suyog — API, runtime, Claude, Fetch.ai agents, Convex, ESP32

**Branch:** `suyog` · **Merge order:** second at every gate · **Mission:** everything moves: time, messages, agents, decisions to people.

## You own
`backend/api/` · `backend/runtime/` · `backend/agent/` · `backend/store/` · `backend/fakes/fake_kitchen.py` · `agents/` · `convex/` ·
`firmware/` · tests in `backend/tests/{api,runtime,agent}`. **Don't edit:** engine/, contracts/, live/, spacetime/, frontend/.

## You provide
| To | What | When |
|---|---|---|
| Ashirwad | Every REST endpoint (S1) on FakeKitchen; `/ws` fallback; OpenAPI for type generation | Phase 1 |
| Kritazya | Run loop calling the facade; context and escalation choices delivered through facade calls | Phase 2–3 |
| Judges | Concierge on ASI:One; agents on Agentverse; README agent table | Phase 3 |

## You consume
Facade (S2) via `FakeKitchen` until Merge 2 · live client (S3) via `fake_live` until Kritazya's is ready · contracts models.

## Phase tasks
**Phase 0** — [ ] Convex account, Agentverse + ASI:One accounts, events API choice (DECISIONS 30), ESP32 kit check
**Phase 1 (12–2 AM)**
- [ ] FastAPI with every endpoint + `/ws` + `/api/health` on `FakeKitchen` (fake decisions + fake escalations)
- [ ] Run loop skeleton (speed, pause, two lanes, shared CustomerSource placeholder), store interface + memory backend
- [ ] Convex schema + function stubs; hello-world uAgent registered on Agentverse
**Phase 2 (2–9 AM)**
- [ ] Real run loop: surges (REST + live client), context injection, both lanes, `compare_lanes`, live publish, Convex batching (`device_blocks`, records)
- [ ] Weather + Grid agents (live + `--recorded`), Concierge context loop → `POST /api/context`, agent log
- [ ] ESP32 bench test (subscribe, LED, ack)
**Phase 3 (9 AM–3 PM)**
- [ ] `runtime/escalations.py`: Claude choice with enum tool, `resolve_escalation`, Proposal when `awaiting_owner`, timeout → leave for default; demo pause
- [ ] Claude agent + tools + templates; proposals + confirm; chat streaming
- [ ] Concierge Chat Protocol: every owner flow in AGENTS.md works in ASI:One; `set_crowd_effect`; Events agent (tier 2)
- [ ] Device bridge: `sim_bridge` mode end to end; README agent names + addresses + badges; run `fetch-compliance`
**Phase 4 (3–9 PM)**
- [ ] Backtest endpoints + progress, results to Convex · ESP32 + INA219 + MOSFET with two stand-in loads, "measured (scaled)"
**Phase 5 (9 PM–4 AM)**
- [ ] Hosted Convex; agents reachable from ASI:One in the cloud; offline fallback on a hotspot; register with the Cal Hacks ASI:One Submission Agent; ASI:One clip for the video

## Definition of done (your scope)
Loop never blocks · every external dependency has a fallback and a warning · Claude only changes state through the two bounded tools ·
every agent message logged · ASI:One owner flow works end to end.

## Session starter
```
ROLE = suyog. Read CLAUDE.md, docs/team/SUYOG.md, docs/ARCHITECTURE.md, docs/CONTRACTS.md, and the design doc for today's
task (API / AGENTS / CONVEX_AND_ESP32). Stay inside my folders. Task: <task>. Restate in ≤5 lines with files and gate; plan if >50 lines.
```
