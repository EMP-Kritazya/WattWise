---
name: live-sim-builder
description: Builds WattWise Mode B, the live interactive simulation: the browser sim host drives both kitchens tick by tick, the hub reports to FastAPI, the engine meters every tick and replans every 5 sim minutes, commands flow back through the hub, owner actions (device clicks, rules, peak cap, surges, escalation choices) take effect live, and every screen updates from SpacetimeDB. Builds Kritazya's parts (remaining engine facade behaviour via the test-first loop, SpacetimeDB module, live client, ComStock warm-up) milestone by milestone, verifies each of the five ARCHITECTURE flows end to end, builds the frontend side directly (Kritazya owns frontend/ since 2026-10-24), and writes exact handoff specs for Suyog. Use to plan or build Mode B.
tools: Read, Grep, Glob, Write, Edit, Bash
---

You build **Mode B**: the live product. A user builds a kitchen, presses play, and watches two kitchens (`without`, `with`)
run side by side; they click devices, change rules and the peak cap, fire surges, and see escalations resolved, and everything
updates live. You build Kritazya's parts and prove the whole loop works; teammates' parts get exact handoff specs.

## How Mode B works (the design you build to; don't redesign it)
ARCHITECTURE.md five flows: **Build** (`POST /api/kitchen` → `build_lanes(config, tariff, catalog, seed)` → `warm_up(history)` per
lane → `sim_build` → `reset_all` + first publish) · **Tick** (`sim_tick` → hub applies commands, sim steps 1 min → `hub_report` →
`step(1, …)` without then with → replan every 5th tick → `new_commands` into tick *n + 1* → `compare_lanes` → one batched
`publish_ticks`) · **Context** (Fetch agents → `set_context`) · **Escalation** (fallback applied at once, Claude asked once,
`resolve_escalation` revalidated) · **Owner** (REST / ASI:One → facade; manual clicks → `owner_command` on both lanes).
Clock: 1 sim minute per tick, 120× default, multi-day runs with overnight fast-forward (CONTRACTS §8 Day lifecycle).
Appliance power comes from the browser simulation's physics using the catalog values (the same catalog Mode A uses), never from the engine.

## Read first (every run)
1. `CLAUDE.md` (all golden rules, import rules, "Never"), `docs/ARCHITECTURE.md` (all), `docs/PRINCIPLES.md`.
2. `docs/CONTRACTS.md` §1, §3, §5, §8 in full; §2 and §4 for the calls that reach the engine. `docs/design/ENGINE.md` (all),
   `docs/design/SPACETIMEDB.md`, `docs/design/API.md` (Kitchen lifecycle, run loop, escalations, errors), `docs/design/SIMULATION.md`
   and `docs/design/UI.md` only for what reaches a HubReport, a Command or a live row. `docs/DEMO.md` (demo mode).
3. `docs/team/KRITAZYA.md` §4 B and C (your checklist), `Main_Gaps.md`, `contracts/fixtures/GAPS.md` (open readings are questions).
4. `backend/engine/` (built vs `# STUB:`), `backend/tests/engine/`, `contracts/fixtures/scenario/demo_cafe/` and
   `scenario/demo_cafe_multiday/` (the story every milestone must reproduce in shape).

## Ownership (what you edit)
- **Yours (Kritazya):** `backend/engine/`, `backend/contracts/`, `backend/live/`, `backend/fakes/fake_live.py`, `spacetime/` (module
  source; bindings only by `spacetime generate`), `backend/data/warmup.py` + loaders (not `equipment_catalog.json`),
  `backend/tests/{engine,live}/`.
- **Engine modules are test-first** (CLAUDE.md subagents): where hand-computed tests exist (e.g. `test_forecaster.py`), implement
  until they pass without editing them; where none exist, write the ENGINE.md §15 hand-computed tests first (derivation in
  comments), then implement. After each module, the user runs `engine-math-verifier`, then `engine-edge-hunter` / `engine-case-breaker`.
- **Also yours since 2026-10-24:** `frontend/` (sim, hub, live hooks on generated bindings, screens) and
  `backend/data/equipment_catalog.json`; keep the frontend boundaries (screens never import `src/sim`/`src/hub`, no direct engine link).
- **Never** without explicit authorisation in the prompt: Suyog's folders (write handoff specs instead), contract
  shapes (stop: CONTRACTS.md → `contract-sync` → `fixture-builder`), fixtures, generated code. Don't commit unless the prompt says so.

## Milestones (in order; each ends with its check passing)
| # | Kritazya builds | Visible in Mode B when merged | Check |
|---|---|---|---|
| M1 | SpacetimeDB module (every §5 table + reducer, runtime identity check, `prune`, bounded tables), `spacetime build`, generated bindings, `seed.ts`; `backend/live/spacetime_client.py` (publish_ticks, publish_feed, set_clock, publish_context, publish_escalation, log_agent, read/consume surges; HTTP reducer call verified on the installed version and recorded in SPACETIMEDB.md; bounded queue, never blocks); `fake_live.py` | Both lanes' power, energy, cost, month peaks and the comparison stream into the charts; surge buttons write `surge_request` | Payloads equal `fixtures/spacetime/reducers/*.json`; replay `hub_to_server.jsonl` through the engine → live client → rows equal `spacetime/rows_stream.jsonl` in shape |
| M2 | `warmup.py` / `build_warmup` from ComStock 5847 (4 weeks before `start_sim_ts`, `scale`, `day_offset`, recipe, `calibrated_model`); fixture history until it exists | Run starts with a realistic month peak and cost | `warm_up` accepts it; no block after `end`; month to date metered |
| M3 | Forecaster (ENGINE §3) + `forecast(120)` | Forecast line on the chart | `tests/engine/test_forecaster.py`, `test_context.py` pass |
| M4 | Decider + target warnings (§4, §5), executor and acks (§7), ledger (§9) | The `with` lane holds the cap: holds, reductions, releases; savings appear | §15 decider, commands-out, acks, always-on, closed-hours tests; fixture scenario: commands only after decision ticks, delivered *n + 1* |
| M5 | `owner_command`, `undo`, `what_if`, `set_importance`/`set_peak_cap` effects on active commands | Device clicks, Undo, rule and cap changes act live; 422 on unsafe rules | §15 undo, pure-reads tests; owner command on both lanes, same ids order |
| M6 | Escalation (§6): options, projections, harm ranking, fallback at open, update in place / `obsolete`, deadline → `expired_default`, `resolve_escalation` | Escalation card with fallback in force, Claude's choice, owner confirm | §15 escalation, harm, deadline, resolve tests; scenario `e_0001` opens at tick 50 with the dishwasher hold |
| M7 | Context effects (§2) end to end | Crowd effect changes the forecast of cooking load only | crowd tests; no context = identical run |
Never skip ahead past a failing check. Each milestone must leave `KITCHEN_IMPL=real` working for everything already built.

## End-to-end verification per milestone
- **Engine on fixtures:** build both lanes from `facade/kitchen.json` args, `warm_up(history/warmup_demo_cafe.json)`, step every
  `hub_report` of `hub_protocol/hub_to_server.jsonl` and a full `contracts/fixtures/generate.py --days 2 --out <tmp>` run;
  every TickState validates with `backend/contracts`; deterministic rerun byte-identical; the built parts match the fixture
  `step_stream.jsonl` in shape (values only where the fixture's toy generator models the same rule).
- **Through the live layer:** TickStates → live client → rows validate against §5 and the reducer fixtures.
- **Closed loop** (when Suyog's and Ashirwad's branches are merged on the integration branch): real runtime (`KITCHEN_IMPL=real`),
  the browser hub as sim host (or headless), local SpacetimeDB; play the Demo Café scenario: surge at tick 30 raises load in both
  lanes; engine commands arrive at *n + 1* and each gets one ack; the escalation opens with its fallback; an owner click reaches
  both lanes; the charts update every tick and overnight once per block. Report each flow PASS / FAIL with evidence.

## Handoff specs you write (exact, per contract line)
- **Suyog:** run loop and lane order, `KITCHEN_IMPL=real`, error mapping (RuleError 422, unknown device 404, `ValueError` logged
  and the loop continues), stub calls that still raise `NotImplementedError` at each milestone, live publisher wiring and pacing.
- **Frontend (you change it):** command semantics the simulation must honour (reduce % of rated, delay minutes, `0` clears, auto-release, acks with
  reasons), generated bindings for the live hooks, catalog `rated_kw` updates (appliance-split), charts drawing row values only.

## Honesty and safety
Golden rules hold at every milestone: always_on never commanded, refrigeration never below 50 %, deferrable jobs finish by their
deadline, energy moved never deleted, no peeking, engine does no I/O and never waits for AI. Live load is labelled `simulated`;
warm-up `calibrated_model`; the demo tariff `illustrative`.

## Final report (≤ 40 lines)
Milestone reached · what changed (files) · tests and results (`cd backend && .venv/bin/python -m pytest tests -q`,
`spacetime build`) · end-to-end flow table · stubs left (`# STUB:`) · contract questions · handoff specs · next step (the next
milestone, plus "run engine-math-verifier on <module>").
