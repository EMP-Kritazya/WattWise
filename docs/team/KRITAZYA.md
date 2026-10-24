# Kritazya — Engine brain, data + proof, SpacetimeDB, Azure backend

**Branch:** `kritazya` · **Merge order:** first at every gate · **Mission:** every number is right, and every screen sees it live.

## You own
`backend/contracts/` · `backend/engine/` (except devices.py, hub.py, customers.py) · `backend/backtest/` · `backend/data/` (except
equipment_catalog.json) · `backend/live/` · `backend/fakes/fake_live.py` · `spacetime/` · `infra/` Container Apps ·
tests in `backend/tests/{engine,backtest,live}`. **Don't edit:** api/, runtime/, agent/, agents/, store/, convex/, firmware/, frontend/,
simulation files.

## You provide (others build against these)
| To | What | When |
|---|---|---|
| Everyone | `backend/contracts/` Pydantic models matching CONTRACTS.md | Phase 1 |
| Suyog | Engine facade (S2): stubs in Phase 1, real by Merge 2/3; `backend/live` client (S3) | Phase 1 stubs |
| Ashirwad | SpacetimeDB module + generated bindings + seed rows (S3); hub interface (S6) the simulation implements | Phase 1 |

## You consume (build against fakes until real)
Simulation via `engine/fake_hub.py` (Ashirwad) · nothing from Suyog (the engine has no I/O).

## Phase tasks
**Phase 0 (before Sat 12 AM)** — [ ] pick ComStock building + county and tariff (DECISIONS 27, 28) · [ ] Azure subscription, resource group
**Phase 1 (12–2 AM)**
- [ ] `backend/contracts/` from CONTRACTS.md + `contracts/ws_messages.schema.json`
- [ ] `engine/__init__.py` exports + facade stubs (`Kitchen` methods raise `NotImplementedError`, shapes correct)
- [ ] SpacetimeDB module: all tables + reducers + identity check + `prune`; `spacetime build`; bindings generated; `seed.ts`
- [ ] **Verify the HTTP reducer call from Python** on the installed version; record DECISIONS 29
- [ ] `backend/live/spacetime_client.py` (publish_ticks, publish_feed, set_clock, publish_context, publish_escalation, log_agent, read/consume surges) + `fakes/fake_live.py`
- [ ] Azure: Container Apps environment + `backend` and `agents` apps (skeleton image), health probe
**Phase 2 (2–9 AM)**
- [ ] Meter (+ hand test) · `step()` wiring with the hub interface · `warm_up()` · `snapshot()` · `owner_command()` · `ingest_reading()`
- [ ] `context.py` + `set_context()` (crowd multiplier, outdoor temp passthrough) · `compare_lanes()` (+ hand test)
- [ ] Publish real ticks through the live client with Suyog at Merge 2
**Phase 3 (9 AM–3 PM)**
- [ ] Forecaster (+ context terms) · target · decider · executor · rules · ledger · undo · `what_if` · `new_commands`
- [ ] `escalation.py`: options, projections, `within_authority`, default, `resolve_escalation`, deadline → `expired_default`
- [ ] All ENGINE.md section 7 tests; run `engine-math-verifier`
**Phase 4 (3–9 PM)**
- [ ] Data loader, distribution recipe, replay (15-min, no peeking), `run_backtest` (3 policies × 12 months, Jan partial, default escalations), checks, sensitivity, cache → Convex via Suyog's endpoint
- [ ] Run `backtest-auditor`; numbers for DEMO.md brackets
**Phase 5 (9 PM–4 AM)** — [ ] Release deploy of `backend` + `agents` on Azure; secrets; probe · [ ] Pitch the Proof part; rehearse

## Definition of done (your scope)
Hand-computed tests pass · engine runs with no network · identical `DEMO_MODE` runs · escalations always resolve (Claude, owner or default) ·
live client never blocks · backtest checks all green.

## Session starter (paste into Claude Code)
```
ROLE = kritazya. Read CLAUDE.md, docs/team/KRITAZYA.md, docs/ARCHITECTURE.md, docs/CONTRACTS.md, and the design doc for
today's task (ENGINE / SPACETIMEDB / DATA_AND_PROOF / AZURE). Stay inside my folders. Task: <task>. Restate it in ≤5 lines
with the files you'll touch and the gate, then plan if >50 lines.
```
