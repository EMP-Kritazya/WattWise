# Tasks

Clock targets are Pacific time. Coding starts about **Sat 12:00 AM**. Devpost deadline **Sun 9:00 AM** (we submit by 8:30).
All code is written during the event. Tick `[x]` only when done **and** tested. Session prompts: `docs/CLAUDE_CODE_PHASES.md`.

| Person | Owns |
|---|---|
| **Kritazya** | Engine brain (facade, meter, forecaster, decider, rules, `compare_lanes`), contracts models, data + proof (replay, backtest), Azure |
| **Suyog** | API + AI (FastAPI, run loop, proposals, Claude agent, Fetch.ai uAgent, store), SpacetimeDB, Convex, ESP32, frontend data layer + chat |
| **Ashirwad** | Simulation (devices, hub, customers, equipment catalog), frontend screens (Builder, Live, feed, approvals, Proof) |

Sleep in shifts: during Phase 2 and Phase 5 at most one person sleeps at a time.

## Before coding
- [ ] Everyone: Claude Code installed + logged in, Python 3.11, Node 20+, repo pulled, `.claude/agents/` present
- [ ] Kritazya: Anthropic API key shared via `.env` (not git), Azure subscription, ComStock file + county, tariff (DECISIONS.md #13, #14)
- [ ] Suyog: Convex account, SpacetimeDB CLI, Agentverse + ASI:One accounts; ESP32 (S3 + PSRAM preferred), INA219, MOSFET modules with headers, breadboard, 5 to 12 V fans/LEDs (no soldering at the venue)
- [ ] Ashirwad: FSTC / ENERGY STAR figures for the equipment catalog

## Phase 0 · Fri 11:00 PM → Sat 12:00 AM · docs reconcile
- [x] Docs aligned with the sponsor stack (Fetch.ai, Claude, SpacetimeDB, Convex + ESP32, Azure); Tiger Data and Hyphenate removed
- [x] `.gitignore` fixed; shared subagents created in `.claude/agents/`
- [x] Contract additions: `new_commands`, `ingest_reading`, Reading, LaneComparison, Proposal, `RuleError` export, SpacetimeDB + Convex tables
- [x] Owners filled in
- [ ] Kritazya: DECISIONS.md #13, #14 filled
- **Gate 0:** team has pulled; `architecture-reviewer` run on docs.

## Phase 1 · Sat 12:00 AM → 2:00 AM · skeleton + seams (in parallel, own folders)
- [ ] Kritazya: `backend/contracts/` models from CONTRACTS.md, generated `contracts/ws_messages.schema.json`, facade stubs, `engine/__init__.py` exports; Azure resource group, Container Apps environment, Static Web App
- [ ] Ashirwad: `equipment_catalog.json` with `default_limits` + `source_note`; interfaces + test skeletons for `devices.py`, `hub.py`, `customers.py`; screen shells (Builder, Live, Proof) on Suyog's mock hooks
- [ ] Suyog: FastAPI with every endpoint + `/ws` + `/api/health`, backed by `FakeKitchen`; run loop skeleton; store interface + memory backend; Vite app scaffold, generated types, `src/mocks`, data hooks; Convex schema + function stubs; SpacetimeDB module (local)
- **Gate 1:** merged to main; UI renders mock ticks; API serves FakeKitchen; `pytest` + `npm run build` pass; SpacetimeDB and Convex answer a hello call. Run `architecture-reviewer`.

## Phase 2 · Sat 2:00 AM → 9:00 AM · simulation
- [ ] Ashirwad: devices + power models (fixed, cycling, demand_driven, job; thermal only if time), seeded customers, hub (HubReport, command delivery + log), handling of delay / reduce / restore / start commands, determinism test
- [ ] Ashirwad: Kitchen Builder complete; Live floor with hub tile; two-lane chart; KPI row from LaneComparison; clock + surge controls
- [ ] Kritazya: meter (+ hand test), `step()`, `warm_up()`, `snapshot()`, `owner_command()`, `ingest_reading()`, `compare_lanes()` wiring the simulation into the facade
- [ ] Suyog: real run loop, two lanes, shared CustomerSource, Convex store batching, SpacetimeDB publisher (one batched call per tick) + surge reads, live data hook switch (SpacetimeDB / `/ws`); ESP32 bench test (subscribe, LED, ack)
- **Gate 2:** `KITCHEN_IMPL=real`; build a kitchen → both lanes run → two browsers see the same kitchen → clicking a device changes both. Run `engine-math-verifier`.

## Phase 3 · Sat 9:00 AM → 3:00 PM · brain + AI + Fetch.ai
- [ ] Kritazya: forecaster, target, decider, executor, rules, owed-energy ledger, approve/undo/what_if, `new_commands` (+ all ENGINE.md section 7 tests)
- [ ] Suyog: decision handling, approval relay + demo pause, proposals + confirm endpoint, Claude agent + tools + template fallback, chat streaming
- [ ] Suyog: Fetch.ai uAgent (Agent Chat Protocol, mailbox, Agentverse, Innovation Lab); whole owner flow in ASI:One; README name + address + badges
- [ ] Suyog: device bridge (commands → Convex, readings → `ingest_reading`), ESP32 fail safe after 30 s; chat drawer + proposal cards
- [ ] Ashirwad: decision feed + undo, approval modal, warning banners, device tiles showing reduced / waiting states; simulation fixes the brain needs
- **Gate 3:** +40 customer surge → `with` lane stays under the cap, every decision explained; owner can ask, approve and undo from ASI:One; engine identical with the AI off.

## Phase 4 · Sat 3:00 PM → 9:00 PM · proof + sponsor depth
- [ ] Kritazya: data loader, distribution recipe, replay (15-min steps, decider every step), `run_backtest` (3 policies × 12 months, January partial), checks, sensitivity, cache; run `backtest-auditor`
- [ ] Suyog: backtest endpoints + progress, results saved to Convex; ESP32 + INA219 + MOSFET switching two low-voltage stand-in loads, "measured (scaled)" end to end
- [ ] Ashirwad: Proof screen + Replay month animation; "measured (scaled)" and hardware badges on tiles
- [ ] Everyone: Devpost draft submitted
- **Gate 4: feature freeze.**

## Phase 5 · Sat 9:00 PM → Sun 4:00 AM · deploy, harden, record
- [ ] Kritazya: Azure Container Apps (min = max replicas = 1, secrets, health probe), Static Web Apps, env wiring to hosted SpacetimeDB + Convex
- [ ] Suyog: hosted SpacetimeDB + Convex deployments; ASI:One reaches the cloud agent; offline fallback (`LIVE_TRANSPORT=ws`, `STORE=memory`) on a hotspot; register with the Cal Hacks ASI:One Submission Agent
- [ ] Ashirwad: `DEMO_MODE=1` preset kitchen; lead 5 clean runs in a row; record and edit the 3 to 5 min video (DEMO.md)
- [ ] Everyone: run `demo-readiness`; Devpost write-up

## Phase 6 · Sun 4:00 AM → 12:30 PM · pitch
- [ ] Rehearse the 2 min table pitch 5+ times (DEMO.md)
- [ ] Devpost final by 8:30 AM (deadline 9:00)
- [ ] Find table number after 9:00; whole team at the table 10:30 to 12:30 with a live demo

## Cut list (in order)
1. Real-meter check (BDG2) 2. Sensitivity extra tariffs 3. Thermal model (use fixed HVAC curve) 4. Payment Protocol
5. Interactive Cards 6. ESP32 loads (keep the LED command demo) 7. 600× speed
Never cut: Builder, two-lane live view, hub, decider + rules, explanations, backtest with checks, ASI:One owner flow,
demo mode + video.
