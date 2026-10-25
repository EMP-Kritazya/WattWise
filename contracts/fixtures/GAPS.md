# GAPS

Readings the fixture builder had to choose because `docs/CONTRACTS.md` / `docs/design/ENGINE.md` leave them open. Each item:
where it shows up, what the fixtures do, and a suggested contract line. Earlier gaps (G01–G67) are decided in `/Main_Gaps.md`.

## Tooling
1. **`backend/contracts/check_fixtures.py` validates every `history/*.json` as `WarmUpHistory`**, so the fixture-only
   `history/daily_inputs.json` (requested by Main_Gaps G59 and named in `docs/team/ASHIRWAD.md`) is reported as FAIL.
   Suggested fix in `checker_for`: `return v(shapes.WarmUpHistory) if p.stem.startswith("warmup_") else None`.
   (`check.py` validates daily_inputs itself; its Pydantic pass skips that one file.) The same function SKIPs
   `shapes/decision_owner_override.json` (no `decision` prefix) and every `scenario/demo_cafe_multiday/*.jsonl`; `check.py`
   validates those with the backend models directly.

## Meter (CONTRACTS §1 Meter, ENGINE §1)
2. **`block_avg_kw` before the block closes.** ENGINE says "block energy ÷ 0.25 h", which mid-block would be a partial value.
   Fixtures: the mean kW of the block's metered minutes so far (equal at the close). Suggested: "`block_avg_kw` = mean kW of the
   block's metered minutes so far; at the close it equals block energy ÷ 0.25 h".
3. **Which day the minute ending at local 00:00 belongs to.** Fixtures: today / this month = the local day / month of the
   minute just metered (`[ts − minutes, ts)`), so the Meter at `ts` 00:00 still shows the finished day and the reset appears at
   `ts` 00:01 (multi-day tick 391). Suggested line in §1 Meter.
4. **Today at the start of a run.** With `month_to_date: null` the engine meters the month's history blocks; fixtures also
   count today's blocks before `start_sim_ts` in `energy_kwh_today` / `cost_usd_today` (247.8 kWh at 17:30), and the demand
   added today is measured from the peaks at local 00:00. Suggested: "metering the history includes today's blocks before the
   start".

## Escalations (CONTRACTS §1 Escalation, ENGINE §6)
5. **`projected.peak_kw` scope.** Fixtures: the problem block's forecast with the option applied, plus any later horizon block
   the option changes (displaced job load); `Decision.effect` peaks stay the 2-h horizon max (so `d_0010` shows 43.1 kW while
   its option shows 42.0 kW for the 18:45 block). Suggested: "`projected.peak_kw` = highest block the option affects, the
   problem block included".
6. **Option action templates and ids.** Template Commands take `command_id`s from the shared `c_` counter (c_0010–c_0012 in
   `e_0001`), are never delivered, and the applied fallback gets new ids (c_0013). Contract says only "templates
   (`decision_id: null`)". Suggested: "template actions consume ids from the shared counter" or "template `command_id: null`"
   (the latter needs a shape change).
7. **"Past `max_reduce_min`" option actions.** `deep_reduce_hvac` keeps both units at their current 40 % beyond 30 min; its
   actions re-state `reduce 40` (same value) so "actions list every affected device" holds. Suggested: say so, or allow an
   explicit "extend" action.
8. **Resolve outside a step.** `resolve_escalation` returns the changed Escalation between ticks; the next `TickState`
   does not repeat it in `new_escalations` (that lists changes made by the step). The runtime publishes the returned object
   (ws `escalation`, `publish_escalation`). Suggested: "a resolve's result is published by the runtime, not echoed in the next
   step".
9. **`active_option_id` after a resolve with a different option.** Fixtures set it to the chosen option (owner example in
   `rest/post_escalation_resolve.json`); the switch Commands follow in the next step. Contract: "only a resolve changes the last".
10. **`expired_default.rationale`.** Fixtures keep Claude's rationale with its pick (`shapes/escalation_expired_default.json`).

## Engine state (CONTRACTS §3 snapshot)
11. **`id_counters` values** — fixtures: the last number issued per type, `{"d": 22, "c": 25, "e": 1}` (not the next one).
12. **`owed_kwh`** — `{device_id: kWh}` for the flexible devices, 3 decimals; the toy ledger uses the `without` lane's
    power of the same device as the unreduced `expected_kw` (an estimate, as ENGINE §9 allows).
13. **Owner commands in TickState.** The owner clicks after step *n*; both lanes' `owner_override` Decisions and Commands
    (`ts` = the click, `rep ts` of tick *n*) appear in step *n + 1*'s `new_decisions` / `new_commands` and are delivered in
    tick *n + 2*. Contract says the Command is in the next step's `new_commands`; it is silent on the Decision. Suggested: "and
    its Decision in that step's `new_decisions`".

## Clock and publishing (CONTRACTS §2 ClockState, §8 Day lifecycle)
14. **`speed` overnight** stays the owner's setting (120); `phase: overnight` says ticks run back to back.
15. **Clock cadence during service** is not specified: fixtures emit ws `clock` / `set_clock` at the start, on every phase or
    `day_index` change, and at `run_complete`; overnight once per closed 15-min block.
16. **Overnight `/ws`**: `tick` ×2 + `comparison` once per closed block (the block-closing tick's TickStates); `decision`,
    `escalation`, `warning` and `context` messages whenever they happen.
17. **Context refresh cadence.** `CONTEXT_INTERVAL_S` is real time, which overnight fast-forward compresses; fixtures post the
    recorded context at ticks 1 and 61, then every 300 sim min, each post carrying 6 hourly values from `history/daily_inputs.json`.

## History and backtest (G59)
18. **`dataset_id` / `scale` for `fixture_synthetic`**: `fixture_synthetic_demo_cafe_v1`, `1.0` (the contract only gives the
    ComStock meaning). Blocks are ordered by `block_start`, then roster order.
19. **July backtest is a partial month** (history ends 2026-07-17 17:30); `BacktestResult` has no partial flag. The toy
    "timer" and "with" policies are fixture code, not `backtest/policies.py`. Suggested: optional `partial: true` or a period field.

## Scenario facts that changed (tell the team)
20. The evening escalation now opens at **tick 50** (not 60); its fallback is applied at once (tick 50, delivered 51) and
    Claude's choice equals the fallback, so there is no `escalation_choice` decision in the streams. `docs/team/ASHIRWAD.md`
    ("escalation at tick 60, Claude's choice delivered at tick 62") and `docs/team/SUYOG.md` ("e_0001 at tick 60 … delivered
    tick 62") need updating.
21. **Sizes.** `scenario/demo_cafe_multiday/` is ~20 MB (the 720 overnight ticks alone are ~12 MB in hub_protocol +
    step_stream, which must carry every tick); `facade/warm_up.json` embeds the 5.9 MB history so FakeKitchen tests can compare
    the exact argument.

## Fixture wrapper fields (not contract shapes)
`rest/*` `status`, `facade/*` `raises`, `ai_tools/*` `input_enum`, `spacetime/reducers/*` `{reducer, args}`,
`convex/functions/*` `{function, type, args, returns}`, `scenario/*`, `history/daily_inputs.json`. The toy simulation's 20 %
physical floor (`MIN_PHYSICAL_PCT`, the clamped-ack example) is fixture-only, not a contract value.
