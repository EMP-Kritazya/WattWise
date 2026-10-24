# Tasks

Hour 0 = hacking start. No code before hour 0 (docs and setup only). Tick `[x]` when done and tested.

| Workstream | Owner |
|---|---|
| Engine (simulation + brain + data + proof) | Kritazya |
| API + AI | ______ |
| Frontend | ______ |

## Before hour 0
- [ ] Repo with CLAUDE.md, README.md, docs/, .claude/agents/ only
- [ ] Everyone: Claude Code installed + logged in, Python 3.11, Node
- [ ] API key, Tiger Data account, ComStock file downloaded, tariff picked (record in DECISIONS.md)

## Phase 0 · hours 0–2 · skeleton + seams (in parallel, own folders)
- [ ] Kritazya: `backend/contracts/` models from CONTRACTS.md, `contracts/ws_messages.schema.json`, `equipment_catalog.json`, `engine/kitchen.py` facade stubs
- [ ] API: FastAPI with every endpoint + `/ws`, backed by `FakeKitchen`; run loop skeleton
- [ ] Frontend: Vite app, generated types, `src/mocks` fake server, page shells (Builder, Live, Proof, Chat)
- **Gate (hour 2):** merged to main; UI renders mock ticks; API serves FakeKitchen; `pytest` runs. Run `architecture-reviewer`.

## Phase 1 · hours 2–10 · simulation
- [ ] Engine: devices + power models, customers, hub, meter (+ meter test), `step()`, `warm_up()`, `snapshot()`, `owner_command()`
- [ ] API: real run loop, two lanes, shared CustomerSource, store batching
- [ ] Frontend: Kitchen Builder complete; Live kitchen floor with hub tile; two-lane chart; clock + surge controls
- **Gate (hour 10):** `KITCHEN_IMPL=real`; build a kitchen in the UI → both lanes run → clicking a device changes the chart. Run `engine-math-verifier`.

## Phase 2 · hours 10–16 · brain + AI
- [ ] Engine: forecaster, target, decider, executor, rules, approve/undo/what_if (+ decider tests)
- [ ] API: decision handling, approval relay + demo pause, AI agent + tools + template fallback, chat streaming
- [ ] Frontend: decision feed + undo, approval modal, warning banner, chat drawer with Confirm cards
- **Gate (hour 16):** a +40 customer surge → `with` lane stays under the cap, every decision explained.

## Phase 3 · hours 16–20 · rest in shifts

## Phase 4 · hours 20–26 · proof
- [ ] Engine: data loader, distribution recipe, replay, `run_backtest` (3 policies × 12 months), checks, sensitivity, cache
- [ ] API: backtest endpoints + progress
- [ ] Frontend: Proof screen + Replay month animation
- [ ] Run `backtest-auditor`
- **Gate (hour 26): feature freeze.**

## Phase 5 · hours 26–31 · harden + record
- [ ] `DEMO_MODE=1`; run `demo-readiness`; 5 clean runs in a row; record video; Devpost write-up

## Phase 6 · hours 31–36 · pitch
- [ ] Rehearse 5+ times (DEMO.md); submit by 8:30 AM Sunday; table by 8:00 AM

## Cut list (in order)
1. Real-meter check (BDG2) 2. Sensitivity extra tariffs 3. Thermal model (use fixed HVAC curve) 4. 600× speed
Never cut: Builder, two-lane live view, hub, decider + rules, explanations, backtest with checks, demo mode + video.
