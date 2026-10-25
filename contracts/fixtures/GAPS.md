# GAPS

Readings the fixture builder had to choose because `docs/CONTRACTS.md` / `docs/design/ENGINE.md` leave them open. Each item:
where it shows up, what the fixtures do, and a suggested contract line. Earlier gaps (G01–G67) are decided in `/Main_Gaps.md`.

## Tooling
1. **`backend/contracts/check_fixtures.py` validates every `history/*.json` as `WarmUpHistory`**, so the fixture-only
   `history/daily_inputs.json` (requested by Main_Gaps G59 and named in `docs/team/ASHIRWAD.md`) is reported as FAIL.
   Suggested fix in `checker_for`: `return v(shapes.WarmUpHistory) if p.stem.startswith("warmup_") else None`.
   (`check.py` validates daily_inputs itself; its Pydantic pass skips that one file.) The same function SKIPs
   `shapes/decision_owner_override.json` (no `decision` prefix), `shapes/tariff_pge_b19.json` (only the exact stem `tariff`),
   `facade/run_backtest_on_progress.jsonl` (no FACADE entry) and every `scenario/demo_cafe_multiday/*.jsonl`; `check.py`
   validates those with the backend models directly. Suggested: a `("tariff", shapes.Tariff)` prefix and a FACADE entry for
   the on_progress events.

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
   the option changes (displaced job load); `Decision.effect` peaks stay the 2-h horizon max, so a fallback Decision's
   `peak_after_kw` can differ from its option's `projected.peak_kw`. Suggested: "`projected.peak_kw` = highest block the option
   affects, the problem block included".
6. **Option action templates and ids.** Template Commands take `command_id`s from the shared `c_` counter (c_0005–c_0006 in
   `e_0001`), are never delivered, and an applied option gets new ids. Contract says only "templates
   (`decision_id: null`)". Suggested: "template actions consume ids from the shared counter" or "template `command_id: null`"
   (the latter needs a shape change).
7. **"Past `max_reduce_min`" option actions.** A `deep_reduce_<type>` that keeps a unit at its current reduction beyond
   `max_reduce_min` re-states that `reduce` (same value) so "actions list every affected device" holds. Suggested: say so, or allow an
   explicit "extend" action.
8. **Resolve outside a step.** `resolve_escalation` returns the changed Escalation between ticks; the next `TickState`
   does not repeat it in `new_escalations` (that lists changes made by the step). The runtime publishes the returned object
   (ws `escalation`, `publish_escalation`). Suggested: "a resolve's result is published by the runtime, not echoed in the next
   step".
9. **`active_option_id` after a resolve with a different option.** Fixtures set it to an accepted Claude option; the switch Commands follow in the next step. Contract: "only a resolve changes the last".
10. **`expired_default.rationale`.** Fixtures keep Claude's rationale with its pick (`shapes/escalation_expired_default.json`).

## Engine state (CONTRACTS §3 snapshot)
11. **`id_counters` values** — fixtures: the last number issued per type, `{"d": 16, "c": 18, "e": 1}` (not the next one).
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
19. **Fake backtest scoring window.** The fixture history starts 2026-05-17, so there are no 4 warm-up weeks before June:
    the fake backtest scores 2026-06-01 → 2026-07-17 17:30 (`partial`: June false, July true = fewer scored days than calendar
    days). The July 17 BacktestPoint has `ts` = end of that local day (contract) although the data stops at 17:30. The toy
    "timer" and "with" policies are fixture code, not `backtest/policies.py`.

## Scenario facts that changed (tell the team)
20. The evening escalation opens at **tick 50** (not 60). Since the HVAC catalog change (8.0 kW units) its rank-1 option is
    `accept_overrun` (0.7 kW over the cap, within authority): the fallback needs no Commands, and Claude's choice equals the
    fallback, so there is neither an `escalation_fallback` nor an `escalation_choice` decision in the streams. `docs/team/ASHIRWAD.md`
    ("escalation at tick 60, Claude's choice delivered at tick 62") and `docs/team/SUYOG.md` ("e_0001 at tick 60 … delivered
    tick 62") need updating.
21. **Sizes.** `scenario/demo_cafe_multiday/` is ~20 MB (the 720 overnight ticks alone are ~12 MB in hub_protocol +
    step_stream, which must carry every tick); `facade/warm_up.json` embeds the 5.9 MB history so FakeKitchen tests can compare
    the exact argument.

## Contract round 2026-10-24 (tariff seasons, demand_peaks, backtest points)
22. **B-19 fixed charge value and unit.** URDB `fixedchargefirstmeter: 11.36882`, `fixedchargeunits: "$/day"` →
    `{"name": "customer_charge", "usd": 11.36882, "per": "day"}` (unchanged; CONTRACTS shows `11.37`, a rounding). The record's
    free-text `basicinformationcomments` quotes a monthly figure (`$19.71253*365/12` mandatory, `$4.59959*365/12` voluntary);
    the fixture uses the structured field only. Suggested: put `11.36882` in the CONTRACTS example and say "from
    `fixedchargefirstmeter` / `fixedchargeunits`".
23. **B-19 energy entry names and split.** URDB energy periods are unnamed and one contract entry holds one `[start, end)`,
    so the six prices need nine entries: `off_peak_winter` (months 1, 2, 10–12: 21:00–16:00; months 3–5: 21:00–09:00 and
    14:00–16:00), `super_off_peak_spring` (3–5, 09:00–14:00), `peak_winter` (1–5, 10–12, 16:00–21:00), `off_peak_summer`
    (6–9, 23:00–14:00), `part_peak_summer` (6–9, 14:00–16:00 and 21:00–23:00), `peak_summer` (6–9, 16:00–21:00). Names are
    the fixture's; the URDB $0 TOU demand period is omitted (no charge). Suggested: list these names in CONTRACTS so
    `backend/data/tariff_urdb.py` produces the same object (`check.py` compares hour by hour against the URDB file).
24. **Optional fields written out.** The demo tariff's energy periods carry `months: null, days: "all"` explicitly (the
    CONTRACTS example omits them on energy, shows them on demand); every Tariff fixture writes every field.
25. **Fixed charges in the Meter.** Fixtures add a per-day charge to `cost_usd_today` / `cost_usd_month` from the first
    metered minute of each local day (warm-up history days of the month included), a per-month charge on the 1st. Zero on
    `demo_tariff_v1`, so no live fixture exercises it. Suggested line in §1 Meter.
26. **Rounding of `demand_peaks`.** `peak_kw` is published to 0.01 kW and `cost_usd = round(usd_per_kw × peak_kw, 2)` on that
    published peak; `cost_usd_month` / `cost_usd_today` use the same published peaks, so `cost_usd_month` = energy + Σ
    `cost_usd` + fixed to the cent. Bills from the meter take `demand_charges` straight from `demand_peaks`; backtest bills
    use 3-decimal peaks (as before).
27. **`on_peak_month_peak_kw` tie.** Two windowed charges with the same rate in one month → the first in tariff order.
28. **`backtest_progress` cadence** in `on_progress` is not specified: fixtures emit it after each quarter of a month's days
    (pct 26/50/76/100 for June). The event carries no `run_id` (contract `{"type", "month", "pct"}`); the runtime adds it.
29. **Authority used by the Demo Café.** The config keeps the ClaudeAuthority example (3 kW / 20 min / 15 min / below-min
    false). The Oct 24 note says the Builder always sends full authority (1000 kW / 0 / 1440 / false); with that, harm uses
    the engine reference for the 0 values and `accept_overrun` would always be within authority. Fixtures apply the other Oct 24
    rule is superseded by G73: Claude sees every ranked option with its authority flag. The engine validates the pick,
    records the verdict in `claude_attempts`, and permits one retry before the deadline. `shapes/escalation_rejected_claude.json`
    illustrates an outside-authority rejection with the fallback still in force. Owner resolution, its Proposal and REST
    endpoint are removed. The Demo Café retains the illustrative 3 kW / 20 min / 15 min authority in its fixtures.

## Fixture wrapper fields (not contract shapes)
`rest/*` `status`, `facade/*` `raises`, `facade/run_backtest.json` `note`, `facade/run_backtest_on_progress.jsonl` (the
`on_progress` event objects in call order), `ai_tools/*` `input_enum`, `spacetime/reducers/*` `{reducer, args}`,
`convex/functions/*` `{function, type, args, returns}`, `scenario/*`, `history/daily_inputs.json`. The toy simulation's 20 %
physical floor (`MIN_PHYSICAL_PCT`, the clamped-ack example) is fixture-only, not a contract value.
