# KRITAZYA.md — your working instructions (Engine + SpacetimeDB + contracts/fixtures + data/proof + Azure backend)

> **Claude Code: this file is Kritazya's instruction set.** Read it first in every session, together with the golden rules in
> `CLAUDE.md`. When this file and a general doc disagree about *what Kritazya builds or may touch*, this file wins.
> Kritazya owns `docs/CONTRACTS.md` and `contracts/`; changing a shared shape still means: CONTRACTS.md → `contract-sync` →
> `fixture-builder` → tell Suyog and Ashirwad.

**Branch:** `kritazya` (create it from `architecture-separation` if it doesn't exist) · **Mission:** every number is right, and
every screen sees it live.

## 1. Your job in one paragraph
You build the **engine**: pure Python that takes each lane's HubReport (the hub's current state) every tick, meters energy and
cost on a real tariff, forecasts, and every 5th tick decides Commands inside the owner's rules; when no such move holds the
peak goal it escalates: it applies the best-ranked option within the owner's authority at once, offers up to 3 evaluated
alternatives, and revalidates Claude's choice with one retry before the deadline. You build
**SpacetimeDB** (module + Python live client), the UI's live source for charts and engine results. You keep the **contracts and
fixtures** that let the other two build without you, and the **backtest** that proves savings on ComStock data + a URDB tariff.

## 2. Scope — exactly what you may edit
| You may create and edit | Never edit (read only) |
|---|---|
| `backend/engine/`, `backend/backtest/`, `backend/data/` (except `equipment_catalog.json`) | `backend/api/`, `backend/runtime/`, `backend/agent/`, `backend/store/`, `backend/fakes/fake_kitchen.py`, `backend/fakes/fake_hub_client.py` |
| `backend/contracts/`, `contracts/` (schema + `fixtures/` via `fixture-builder`) | `agents/`, `convex/`, `firmware/` |
| `backend/live/`, `backend/fakes/fake_live.py`, `spacetime/` | `frontend/`, `backend/data/equipment_catalog.json` |
| `backend/tests/{engine,backtest,live}/`, `infra/` Container Apps | Docs: `CONTRACTS.md`, `Main_Gaps.md`, `design/ENGINE.md`, `design/SPACETIMEDB.md`, `design/DATA_AND_PROOF.md`, `design/AZURE.md`, this file; other docs only to keep them in sync with a contract change, announced to the team |

## 3. Rules for this phase (independent development)
1. **Build only against the fake data** in `contracts/fixtures/` (section 5) for everything you don't own. The engine never
   imports from api/, runtime/, agent/, store/, live/, and never does I/O (golden rule 7).
2. **Do not merge** anything or pull teammates' branches into yours. Commit to `kritazya` only. Integration comes later, on your call.
3. **Contract changes are the only structural changes you make**, and only through the sequence above. Don't touch other people's code.
4. **Never hand-edit fixtures**: change `generate.py` (via `fixture-builder`), regenerate, run `check.py`.
5. Fixture numbers are illustrative; never show them as savings. Real numbers only from tested engine code + `backtest-auditor`.

## 4. What to build (in order; tick when done and tested)
**A. Shared foundations (unblocks everyone's real integration later)**
- [ ] `backend/contracts/` Pydantic v2 models for every CONTRACTS.md shape + `contracts/ws_messages.schema.json` (viewer `/ws` + `/ws/hub`); validate every fixture with them
- [ ] Work through `Main_Gaps.md` (repo root): every gap has a demo decision in CONTRACTS.md; redesign the ☐ rows, then CONTRACTS.md → `contract-sync` → `fixture-builder`
- [ ] `engine/__init__.py` exports (`Kitchen`, `run_backtest`, `compare_lanes`, `RuleError`) + facade stubs with correct shapes

**B. SpacetimeDB** — design: `docs/design/SPACETIMEDB.md`, CONTRACTS.md §5
- [ ] Module: every table + reducer, runtime identity check, `prune`; `spacetime build`; generated TS bindings; `seed.ts` from `fixtures/spacetime/tables/`
- [ ] Verify the HTTP reducer call from Python on the installed version (record the result in `docs/design/SPACETIMEDB.md`)
- [ ] `backend/live/spacetime_client.py` (publish_ticks, publish_feed, set_clock, publish_context, publish_escalation, log_agent, read/consume surges), never blocking; `fakes/fake_live.py`; payloads equal `fixtures/spacetime/reducers/*.json`

**C. Engine** — design: `docs/design/ENGINE.md` (decided 2026-10-24; open: Main_Gaps Q4, Q5)
- [x] Decide and document (ENGINE.md, CONTRACTS.md, Main_Gaps.md C + I): warm-up = ComStock `WarmUpHistory` · `minimize` target = highest peak of the previous 4 same weekdays · power-only planning model (no HVAC thermal model this build) · escalate when a block within 30 min can't be held; fallback applied at once; harm ranking
- [ ] Run `contract-sync` then `fixture-builder` for the 2026-10-24 contract changes (Meter, TickState warnings, Escalation, Command, ClockState, WarmUpHistory, SpacetimeDB columns) and send the team notice
- [ ] Multi-day runs + fake history (Main_Gaps J, G56–G60): `contract-sync` → `fixture-builder` (`history/`, `scenario/demo_cafe_multiday/`, `generate.py --days N`) → team notice
- [ ] Engine build loop per module: `engine-test-author` → `engine-builder` → pytest → `engine-math-verifier`; then `engine-edge-hunter` until clean; `architecture-reviewer`
- [ ] Meter (+ hand test): energy, 15-min blocks, month peak, energy price now, cost today/month on the tariff
- [ ] `step(1, hub_report)` on fixture HubReports; acks consumed; decisions only on `tick_id % 5 == 0`; Commands out in `new_commands`
- [ ] Context (`set_context`), forecaster, decider, rules (limits are hard: e.g. `must_finish_by`), ledger, undo, `what_if`, `compare_lanes`
- [ ] Escalation: options, projections, `within_authority`, harm ranking, fallback at open, update in place / `obsolete`, `resolve_escalation` revalidation, deadline → `expired_default`
- [ ] `backend/data/warmup.py` + `build_warmup`: ComStock → `WarmUpHistory` for the Demo Café (scale, day_offset, recipe)
- [ ] All ENGINE.md §15 hand-computed tests; run `engine-math-verifier`

**D. Data + proof** — design: `docs/design/DATA_AND_PROOF.md`
- [ ] Pick the ComStock building + county and the URDB tariff (same region); loader, distribution recipe, replay (no peeking), `run_backtest` (without / timer / with × 12 months), checks, sensitivity; run `backtest-auditor`

**E. Azure** — design: `docs/design/AZURE.md`
- [ ] Container Apps `backend` + `agents` (1 replica each), secrets, health probe

## 5. Your fake data (all in `contracts/fixtures/`, which you own)
| You need | Use this |
|---|---|
| Engine input (what the browser hub sends) | `hub_protocol/hub_to_server.jsonl` (120 ticks × 2 lanes), `shapes/hub_report_*.json`, `shapes/command_ack_*.json` |
| Expected output shapes (not values) | `facade/step_stream.jsonl`, `facade/*.json`, `shapes/tick_state_*.json`, `shapes/escalation_*.json`, `shapes/meter.json` |
| Context the engine receives | `shapes/context.json`, `agents/context_post.json` |
| SpacetimeDB rows + reducer args | `spacetime/tables/*.json`, `spacetime/reducers/*.json`, `spacetime/rows_stream.jsonl` |
| Scenario + open questions | `scenario/demo_cafe/`, `README.md`, `GAPS.md` |
| Warm-up history + multi-day streams | `history/warmup_demo_cafe.json`, `scenario/demo_cafe_multiday/`, `generate.py --days N` (next `fixture-builder` run) |

## 6. Big-picture docs
`docs/ARCHITECTURE.md` · `docs/CONTRACTS.md` (all; you own it) · `docs/design/ENGINE.md` · `SPACETIMEDB.md` · `DATA_AND_PROOF.md` ·
`AZURE.md` · `docs/PRINCIPLES.md`. Teammates' instructions: `docs/team/SUYOG.md`, `docs/team/ASHIRWAD.md`.

## 7. Checks before you say "done"
`pytest backend/tests/{engine,backtest,live}` passes · hand-computed tests included · engine runs with no network · identical
`DEMO_MODE` runs · escalations always resolve (Claude or default) · live client never blocks · `spacetime build` passes ·
`python3 contracts/fixtures/check.py` passes after any contract change · backtest checks all green before any savings number.

## 8. Out of scope — do not do these
FastAPI, run loop, Claude prompts/tools, Fetch agents, Convex, firmware, frontend code · editing teammates' folders · merging or
rebasing with other branches · shape changes that skip CONTRACTS.md → `contract-sync` → `fixture-builder`.

## 9. Session starter (paste into Claude Code)
```
ROLE = kritazya. Read docs/team/KRITAZYA.md first (it is my instruction set), then CLAUDE.md golden rules, and only the docs it
lists for today's task. Build only inside my scope, against contracts/fixtures/ for anything I don't own. Do not merge, do not
edit teammates' folders. Task: <task>. Restate it in ≤5 lines with the files you'll touch and the fixtures you'll use; plan
first if >50 lines. End with: what changed, tests run, stubs, contract changes, next subagent.
```
