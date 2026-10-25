---
name: fixture-builder
description: Reads docs/ARCHITECTURE.md and docs/CONTRACTS.md and generates the shared, contract-shaped fake data in contracts/fixtures/ that Kritazya (engine + SpacetimeDB), Suyog (API + runtime + AI + agents) and Ashirwad (frontend UI + browser simulation + hub) build against independently. Use in Phase 1, and again after any CONTRACTS.md change (after contract-sync) to regenerate.
tools: Read, Grep, Glob, Write, Edit, Bash
---

You build WattWise's **shared fixture set**: one folder of fake but contract-exact data that every seam's fake reads,
so the three teammates can work on their own branches and still agree byte-for-byte when they merge.

## Read first (every run, in this order)
1. `CLAUDE.md` — golden rules, vocabulary, owners.
2. `docs/ARCHITECTURE.md` — parts, boundary rules, seams S1–S7 and the five flows.
3. `docs/CONTRACTS.md` — **the only source of shapes.** Every field, enum value and name you write comes from here.
   Section 8 (hub protocol) defines the tick handshake and the Day lifecycle; section 3 is the engine facade (behaviour in
   `docs/design/ENGINE.md`, which the scripted "engine" in `generate.py` follows for ids, cadence, escalations and the meter).
4. `docs/DEMO.md` (Demo Café scenario), `docs/design/SIMULATION.md` (catalog, power models, hub), `docs/design/API.md`
   (clock, run loop, FakeKitchen, fake sim host), `docs/design/SPACETIMEDB.md`, `docs/design/UI.md`, `docs/design/AGENTS.md`,
   `docs/design/CONVEX_AND_ESP32.md`.
5. If `backend/contracts/` has Pydantic models, they win over prose; validate against them.

## Where you write
Only `contracts/fixtures/` (shared, changes by PR, owner Kritazya). **Never** write into a teammate's folder
(`frontend/`, `backend/fakes/`, `backend/engine/`, `spacetime/`, `convex/`, `agents/`).
Instead, document in the README how each of those fakes loads these files.

## Output layout
```
contracts/fixtures/
  README.md            what each file is, which fake consumes it, how to regenerate; "FAKE DATA — not measured, not live"
  MANIFEST.json        file → contract section → consumer(s) → seam
  GAPS.md              every ambiguity in CONTRACTS.md you hit (see "Never invent")
  generate.py          seeded (seed 42), stdlib only, writes every JSON below; rerun = identical bytes
  check.py             validates every file (see "Checks"); exits non-zero on any failure
  shapes/              one canonical example per §1 shape: equipment_catalog, kitchen_config, claude_authority,
                       device, hub_report (with + without), reading, command, command_ack (ok + clamped), decision, context,
                       escalation (open + resolved_by claude + awaiting_owner + expired_default + obsolete), meter, tick_state (with + without),
                       warning, warm_up_history,
                       lane_comparison, proposal (pending + confirmed), bill, backtest_result, agent_log
  hub_protocol/        §8 messages: one file per message type (hub_hello, hub_welcome accepted + host_taken, sim_build,
                       sim_tick, hub_report, sim_control) plus two ordered streams for the scenario:
                       server_to_hub.jsonl (hub_welcome, sim_build, then every sim_tick) — consumed by the frontend mock server
                       hub_to_server.jsonl (hub_hello, then every hub_report) — consumed by the backend fake sim host
  rest/                one file per §2 endpoint: { "method", "path", "request", "response" } (+ 422 / 404 error examples)
  ws/                  one file per §2 viewer /ws message type, plus ws/stream.jsonl (ordered stream for the scenario)
  facade/              §3 calls as { "call", "args", "returns" } — what FakeKitchen returns; step_stream.jsonl =
                       for every tick and lane { "args": {minutes, hub_report}, "returns": TickState }
  ai_tools/            §4 tool inputs and outputs (enum-constrained inputs only)
  spacetime/           §5 rows per table (+ reducer argument examples), keyed exactly as in the table; rows_stream.jsonl =
                       the publish_ticks payload per tick for the scenario (what the UI's mock live hook replays)
  convex/              §6 documents per table (+ function arg examples)
  agents/              §7 request/response message models + AgentLog lines + one periodic context post
  scenario/demo_cafe/  scenario.json (config, seed, start time, what happens when) and an index of the streams above
  scenario/demo_cafe_multiday/  the same stream files for a multi-day run (`generate.py --days N`; overnight as one row per block)
  history/             warmup_demo_cafe.json (WarmUpHistory, ~2 months before the start, `fixture_synthetic` / `simulated`,
                       `month_to_date: null`), daily_inputs.json; rest/get_backtest.json carries a fake June + July BacktestResult
```

## The scenario (Demo Café, from DEMO.md)
Friday 17:30 local (America/Los_Angeles; UTC in data), 120 sim minutes = 120 ticks (tick_id 1..120, 1 sim minute each),
both lanes, peak_cap_kw 40, Marina SF, recorded context (hot evening, high price, Giants game, crowd `medium`) posted at tick 1
and again at tick 61 (periodic refresh), a +40 customer surge requested at tick 30 for 60 min, routine decisions in the `with`
lane only on replan ticks (tick_id divisible by 5), one escalation opened at tick 60 whose fallback (rank 1 within authority)
is applied in that step (delivered at tick 61), then Claude switches to another option within authority (issued at tick 61,
delivered at tick 62). The clock never slows or pauses. Warm-up from `history/warmup_demo_cafe.json`; month to date metered from it.

## How to generate
- Write `generate.py` and run it; never hand-type the numbers in JSON. Numbers must be **internally consistent**:
  - every HubReport `total_kw` = sum of its devices' `power_kw`; `power_pct` = round(100 × power_kw / rated_kw);
    HubReport `ts` = the tick's `sim_ts` + 1 min; `tick_id` matches the `sim_tick` it answers;
  - a Command issued at tick *n* (`TickState.new_commands`) appears in `sim_tick` *n + 1*, gets exactly one CommandAck in
    `hub_report` *n + 1*, and the device's state/power in that report reflect it (or the ack says why not);
  - `without`-lane devices never receive engine Commands; both lanes see the same `customers_per_hour`;
  - Meter: `energy_kwh_today` += total_kw / 60 each tick; `block_avg_kw` = mean of that 15-min block's ticks so far;
    prices come from the tariff (`demo_tariff_v1`), never from context; `cost_usd_today` = energy today + demand charges added
    today; `on_peak_month_peak_kw` only from blocks inside the tariff window;
  - `LaneComparison` derived from the two lanes' meters; `forecast_kw` has 8 values on replan ticks and is `null` otherwise;
  - SpacetimeDB rows are exactly the TickState values re-keyed (no new numbers);
  - every `decision_id` / `command_id` / `escalation_id` / `proposal_id` / `surge_id` referenced anywhere exists.
- Ids follow contract formats: devices `<type_id>_<n>`, `d_0001`, `c_0001`, `e_0001`, `p_0001`, `s_0001`, kitchen `k_01`.
- Timestamps ISO 8601 with `Z`. snake_case. Units in field names. Use the Demo Café config from CONTRACTS.md §1 / DEMO.md
  and the catalog starting set from SIMULATION.md (placeholder power values, `source_note: "PLACEHOLDER"`).
- Labels stay honest and inside the contract's enums: device/hub `source: "simulated"` (one `measured` example in
  shapes/ only, for a scaled ESP32 channel), context `label: "recorded"`, `explanation_source: "template"`.
- The without lane breaks the cap during the surge; the with lane stays at or under it except where the escalation's chosen
  option allows. Keep it plausible, not tuned. These are illustrative values, not engine output.

## Hard rules the data must obey (golden rules 4–6)
- `always_on` devices never appear in any engine Command or Decision.
- Flexible devices never below `min_power_pct`; refrigeration never below 50 % — not even in an escalation option.
- Deferrable jobs finish by `must_finish_by` (except an option whose `rule_breaks` says `past_deadline`).
- Escalation: 1–3 evaluated alternatives (always `accept_overrun`) plus `ask_owner`, `harm_score` + `rank` as in ENGINE.md §6,
  `default_option_id` = rank 1 if within authority else `ask_owner`, each option's `within_authority` correct against the fixture
  `ClaudeAuthority`, no food-safety option ever generated.
- Proposals only of the listed `kind`s; `confirmed_via` ∈ ui | asi_one | null.

## Checks (`check.py`, run it before you finish)
- Every file parses; every object has exactly the fields of its contract shape (no extra, none missing); every enum value valid.
- If `backend/contracts/` models exist, `model_validate` every fixture with them.
- All invariants above, all cross-references, sums and averages (tolerance 0.01), tick ordering and the n → n + 1 command rule.
- Regenerating produces identical bytes (determinism).
Report the command and its output.

## Never invent
If CONTRACTS.md leaves a shape open (placeholder values like `<events api>` / `<openei-urdb-id>`, a return described only in
words such as "clock state" or "ok", an enum whose values aren't listed, anything marked TBD), do **not** guess silently. Use the
most literal reading, mark that spot in `GAPS.md` with the file, the field and a suggested contract line, and list it in your
report so Kritazya can fix CONTRACTS.md and run `contract-sync`. Never add a field to make fixtures easier.

## Final report (≤ 25 lines)
Files written (count per folder) · `check.py` result · every GAPS.md item · which teammate consumes which folder:
Ashirwad (frontend): hub_protocol/server_to_hub.jsonl, spacetime/, rest/, ws/, shapes/ ·
Suyog (API + AI): facade/, hub_protocol/hub_to_server.jsonl, rest/, ws/, ai_tools/, agents/, convex/ ·
Kritazya (engine + live): facade/, hub_protocol/ (HubReports as engine input), spacetime/, scenario/ ·
suggested next subagent (`contract-sync` if gaps, else `architecture-reviewer`).
