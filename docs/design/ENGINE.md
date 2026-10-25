# Design: Engine brain (owner: Kritazya)

## Principles

- Every number is computed here and covered by a hand-computed test.
- Routine moves every 5 sim minutes inside the owner's rules; escalations only when that's impossible.
- Never waits for AI: an escalation applies its safe fallback the moment it opens; Claude can only switch it, in time and within authority.
- No I/O: history, context and HubReports come in, Commands go out, all as plain objects. No wall-clock time.
- Energy moved, never deleted (ledger). Food-safety floor is absolute.
- Keep only the state future decisions need (rolling 4-week block history, month-to-date, active commands, ledger, open
  escalations, recent decisions, id counters). Full readings and decision logs live outside the engine (SpacetimeDB, Convex, backtest output).

> **Status:** engine decisions are made (Main_Gaps.md sections C, I, J and K). Shapes are in CONTRACTS.md; this file is how the
> engine works inside. **Not in this build:** indoor-temperature (HVAC thermal) model, weather in the forecast, a learned
> customer forecast, engine state surviving a backend restart (section 14).

**Boundary.** The engine sees the kitchen only as the HubReport the runtime passes to `step(1, hub_report)` (the browser hub's
state of that lane for the minute just simulated). It changes the kitchen only by returning Commands in `TickState.new_commands`;
the runtime delivers them to the hub in the next `sim_tick`. Real ESP32 readings arrive through `ingest_reading()`.
The appliance physics lives in the browser (`frontend/src/sim/`). The engine's planning model is power-only (kW per device per
15-min block); it has no thermal model in this build, so `projected.max_indoor_temp_change_c` is `null` ("not modelled").
Escalation is the only path to Claude: the engine emits an Escalation, the runtime asks Claude, the engine revalidates the answer.

All local times (days, months, tariff windows, `must_finish_by`, opening hours) are in `tariff.timezone`.

## 0. Lanes, ids and warm-up

- `Kitchen.build_lanes(config, tariff, catalog, seed)` → `{"without": Kitchen, "with": Kitchen}` sharing one id allocator.
  (`Kitchen(config, tariff, catalog, control, seed, ids=None)` still works for tests; `ids=None` gives the lane its own allocator.)
  `catalog` = list[EquipmentType] passed in by the runtime (the same `equipment_catalog.json` the simulation gets in `sim_build`);
  the engine takes each device's `category`, `power_model`, `rated_kw` and `params` (e.g. `cycle_min`) from it and keeps no copy.
- **Ids:** one monotonically increasing counter per id type, shared by both lanes: `d_0001` (Decision), `c_0001` (Command),
  `e_0001` (Escalation); zero-padded to 4 digits, wider when needed (`d_10000`). Never reset during a run; a new kitchen starts at 1.
  Determinism comes from a fixed order: every tick the runtime steps `without`, then `with`, and calls any id-creating facade
  method (`owner_command`, `undo`, `resolve_escalation`) on `without` before `with`. Counters are in `snapshot()["id_counters"]`.
- **Warm-up:** `warm_up(history)` is called once per lane after construction and before the first `step`. `history` is a
  `WarmUpHistory` (CONTRACTS.md section 1): 15-min per-device blocks for the 4 weeks before the start, built by
  `backend/data/warmup.py` from NREL ComStock (scaled to the kitchen, label `calibrated_model`; see DATA_AND_PROOF.md), plus
  optional `month_to_date`. Every block must end at or before the start (`block_start + 15 min ≤ start`) or `warm_up` raises
  `ValueError` (no peeking). `month_to_date: null` → the engine meters the history blocks from the 1st of the month up to the
  start on the tariff, so the run begins with realistic month-to-date peaks and cost. A non-null `month_to_date` is used as-is;
  it is reserved for resuming after a backend restart, which this build doesn't do, so the runtime always passes null (a `reset`
  or a new kitchen restarts from the warm-up; reading the old `live_tick` row back would double-count).
- **Fake history until ComStock:** `contracts/fixtures/history/warmup_demo_cafe.json` (next `fixture-builder` run) is a `WarmUpHistory` with
  `source: "fixture_synthetic"`, `label: "simulated"`, covering about 2 months before the start. The engine treats it exactly like
  the real one: the forecaster and the `minimize` target read only the last 4 weeks; month to date is metered from the current
  month's blocks only. So the engine built on fakes runs the same code path as on real data.
- **Multi-day runs:** a run is `run_days` service days with every closed-hours minute ticked too (CONTRACTS.md section 8, Day
  lifecycle). The engine has no notion of phases: overnight ticks are metered and replanned like any other tick (local day and
  month boundaries in section 1 already handle midnight and the 1st). Outside `operating_hours` it starts no reductions and no
  holds (section 5), so overnight it meters, forecasts and, only if a block is still over the target, escalates.
- **No warm-up file** (or `warm_up` never called): the forecaster uses live history only (section 3 fallbacks), the `minimize`
  target falls back to the month peak so far, and month-to-date starts at zero. The engine never blocks on it.

## 1. Meter (`engine/meter.py`)

- `HubReport.ts` is the end of the minute just simulated; that minute is `[ts − minutes, ts)`.
- `total_kw` = sum of `devices[].power_kw` after any measured override (equals the hub's `total_kw` when nothing is measured).
- Energy: `energy_kwh += total_kw × minutes / 60`, added to today, this month and the open 15-min block.
- Energy price of a minute: the one tariff `energy` period matching the minute's local start (month, day type, time; CONTRACTS.md
  Tariff "Seasons, days and windows"). `price_usd_per_kwh_now` = price of the minute starting at `ts`. Context grid prices never set the bill.
- **Blocks** are aligned to local :00/:15/:30/:45. A block closes when `ts` reaches `block_start + 15`. `block_avg_kw` = block
  energy ÷ 0.25 h (minutes not metered count as 0; the demo starts on a block boundary).
- **Peaks (G36, generalised 2026-10-24 for seasonal tariffs such as PG&E B-19):** the engine keeps one month peak **per demand
  charge**, any number of charges. When a block closes, for every charge that applies in the block's local month and whose day
  type matches: if `windows` is null or the block's local start is in any `[start, end)` window,
  `peak_c = max(peak_c, block_avg_kw)`. `month_peak_kw` = the highest closed block of the month (any hour);
  `on_peak_month_peak_kw` = `peak_c` of the highest-rate windowed charge that applies this month (null if none);
  `demand_peaks` lists every applicable charge with `peak_kw` and `cost_usd`.
- **Day** = local midnight to midnight; **billing month** = local calendar month. Every peak resets at local 00:00 on the 1st.
  DST days simply have 92 or 100 blocks.
- `cost_usd_today` = energy cost today + demand charges **added** today `Σ_c rate_c × (peak_c now − peak_c at today's 00:00)` +
  today's fixed charges. (So a peak set today shows up in today's cost and in `LaneComparison.saved_today_usd`.)
- `cost_usd_month` = energy cost month to date + `Σ_c rate_c × peak_c so far` (applicable charges) + fixed charges to date.
- `Bill(period)`: `energy_kwh`, `energy_cost_usd`, one `demand_charges` entry per charge applicable in that month (`name`,
  `peak_kw`, `cost_usd`), `fixed_usd`, `total_usd`. Projections, snapshots, decision effects, escalation projections and backtest
  results use the same per-charge function, so a summer `peak_demand_summer` of $46.16/kW weighs in every decision exactly as it bills.

## 2. Context (`engine/context.py`)

- `set_context(context)` merges structured context (CONTRACTS.md); used from the next step. Plain object; the engine never fetches it.
- **Crowd effect** → multiplier none 1.00 · small 1.10 · medium 1.25 · large 1.40, applied to the forecast of `demand_driven`
  devices (the customer-driven cooking load). The runtime also passes it to the simulation in `sim_tick.inputs`.
- **Prices** → tie-break only: among moves with equal peak effect, prefer the cheaper tariff hour, then the lower context price.
- **Weather** → kept and returned in `snapshot()`; not used by the forecast in this build (no HVAC model).
- Missing or stale context → last known value, then multiplier 1.00. No context at all → identical run to before context existed.
- **Customers are not predicted.** The engine forecasts kW, not customers. The weekday × time-of-day load history already
  carries the usual lunch and dinner rush; the live ratio (section 3) corrects today's level; `crowd_effect` (Claude's category
  from the Fetch events agent) scales the customer-driven load. `customers_per_hour` is only echoed.

## 3. Forecaster (`engine/forecaster.py`)

- Per device, per 15-min block, next 120 min: 8 blocks; block 0 is the block in progress (its metered minutes + forecast for the rest).
- **Base:** mean `avg_kw` of that device at the same weekday and local block time over the previous 4 weeks (warm-up blocks + the
  engine's own closed blocks; only blocks that ended before now). Fewer weeks → mean of what exists; none → the device's last
  closed block; none → its current `power_kw`.
- **Live ratio:** `ratio = actual / base` over the last 2 closed blocks for the `always_on` devices together (they are never
  commanded, so commands don't bias it), clamped 0.5–2.0, applied to `always_on` and `flexible` forecasts for the next hour,
  fading linearly to 1.0 over the second hour.
- **Crowd multiplier** on `demand_driven` devices (section 2).
- **Commanded devices:** a reduced flexible device → `min(base, value% × rated_kw)` until its planned restore, then base plus
  catch-up (`owed_kwh × 4` added to the first block after restore, capped at `rated_kw`). Job devices → section 5.
- `forecast_kw` (TickState) = per-block sum over devices, computed on decision ticks. `forecast(horizon_min)`: `horizon_min` is
  fixed at 120 in this build (anything else → `ValueError`); returns the latest decision tick's forecast, no recomputation.
- `unavoidable_kw` per block = `always_on` forecast + each flexible device at `min(forecast, min_power_pct% × rated_kw)` + running
  jobs + jobs that can no longer move (deadline-forced).
- **No peeking:** the history view raises if anything reads a block that ends after now.

## 4. Target (`engine/decider.py`)

```
cap mode:      target_kw = peak_cap_kw
minimize mode: target_kw = highest closed-block avg kW over the 4 most recent same-weekday local days before today
               (history, no peeking); fixed for the whole local day; a hard limit exactly like a cap.
               No history for those days → month_peak_kw so far; nothing closed yet this month → no reductions until a block closes.
any mode:      if unavoidable_kw of a block > target_kw → TickState warning cap_unreachable
               {unavoidable_kw, peak_cap_kw, target_kw} (once per block, on the decision tick it first appears), plan that
               block against unavoidable_kw, and escalate (section 6).
```

The `without` lane computes the same `target_kw` for display and never acts on it.

## 5. Decider (`engine/decider.py`) — `with` lane, decision ticks only

Runs when `tick_id % 5 == 0` (live) or on every step (replay, 15-min steps). Plans a **desired state** per controllable device and
emits Commands only where it differs from the active state (never re-sends a command with the same value).

```
forecast = forecaster.next_2h()          # with active commands and the ledger already applied
for each block over target_kw, earliest first:
    excess = block_kw − target_kw
    1. HOLD deferrable jobs expected in this block → release in the earliest later block with room
    2. REDUCE flexible devices active in this block, largest reducible kW first (ties: device_id)
    3. never touch always_on, protected devices (owner/undo, 30 sim min), or devices whose command was rejected this block
    stop when excess ≤ 0
still over target after every in-rules move, and block starts within 30 min → escalation (section 6)
RELEASE held jobs whose block now has room · RESTORE reductions no longer needed or at their time limit
```

Delaying goes first (no comfort impact). Ties are broken by tariff price, then context price, then `device_id`.

**Jobs (deferrable).** The engine can't see when the simulation will trigger the next job (dirty racks, ice level), so:

- An idle, unheld job device contributes its history base (an expected-value kW) to each block. A `waiting` job is a known job:
  `rated_kw` for `cycle_min`, placed where the plan releases it. A `running_job` is never commanded (the hub rejects it).
- HOLD = `delay` with `value` = minutes from delivery until the planned release. On an idle device it holds the next job; on a
  waiting job it replaces the hold. The hub releases the job by itself when the hold ends, so the deadline never depends on
  engine timing. The engine re-sends `delay` (replace) to move the release, or `start` to release early when room appears.
- Bounds: total hold, counted from the first delay the hub applied, ≤ `max_delay_min`; release + `cycle_min` ≤ effective
  deadline = `min(must_finish_by, close)` local today. A job that can't satisfy both is not delayable. Holds start only during
  `operating_hours`.
- Hold expires with no job triggered → nothing to do.

**Reductions (flexible).**

- `reduce` value = % of `rated_kw` (the device draws at most `value% × rated_kw`), integer, rounded up, ≥ `min_power_pct`;
  reduce only what the excess needs.
- Consecutive reduced time ≤ `max_reduce_min`: reduce issued at tick t (applied t+1) → `restore` issued at the decision tick
  t + 5k with `k = floor(max_reduce_min / 5)`, or earlier when no longer needed. A new value replaces the old one; the reduced
  time keeps counting from the first reduce.
- Cooldown: after a restore the device is not reduced again for `max_reduce_min`. No new reduce starts in the last
  `max_reduce_min` before close or while closed, so catch-up happens while open.

**Effect of a decision** (`Decision.effect`), computed marginally in plan order so one replan's savings add up without double counting:

```
baseline  = horizon forecast with every earlier move of this replan applied
optimized = baseline + this move
peak_before_kw = max block of baseline ; peak_after_kw = max block of optimized
cost(x) = Σ_c rate_c × max(peak_c(x), month_peak_c) + energy cost of x over the horizon (moved energy at its new block's price)
cost_delta_usd = optimized_cost_usd − baseline_cost_usd ;  saving_usd = −cost_delta_usd
```

`peak_c(x)` uses only the blocks inside charge c's window. Only a peak above what the month has already paid for costs money.

`reason_code`: `stay_under_cap` (cap mode) or `avoid_new_peak` (minimize mode) for holds and reductions · `release_into_valley`
(start / release) · `catch_up` (restore) · `owner_override` · `escalation_fallback` · `escalation_choice`.

## 6. Escalation (`engine/escalation.py`)

**Open** on a decision tick when a block starting within the next 30 sim minutes (the block in progress included) is still over
`target_kw` after every in-rules move (`problem.forecast_peak_kw` = that forecast, `excess_kw` = it − target). At most one **active** escalation (`open` or `awaiting_owner`) per lane per `block_start`.

**Options** (on the residual problem):

- `accept_overrun` (always): no actions; the peak the in-rules plan leaves.
- `deep_reduce_<type_id>`: that type's flexible devices below `min_power_pct` and/or past `max_reduce_min`, by the least amount
  that holds the target (or to their floor). Never below 50 % for refrigeration; food-safety breaks are never generated.
- `extend_delay_<type_id>`: that type's jobs past `max_delay_min` and/or `must_finish_by`, by the least amount that holds the target.
- One best (lowest-harm) `deep_reduce_*` and one best `extend_delay_*` are kept → 1–3 alternatives (2–3 whenever the kitchen
  has a flexible or deferrable device left to move), plus `ask_owner`.

**Projection** of each alternative, re-forecasting with it applied:
`peak_kw` · `cost_delta_usd = optimized_cost_usd − baseline_cost_usd`, where baseline = the in-rules plan with the problem block
held exactly at the target (hypothetical, no rule broken), so it is the extra cost of the option · `max_indoor_temp_change_c: null`
· `rule_breaks` with amounts (G13 kinds).

**`within_authority`** (ClaudeAuthority): `cap_overrun ≤ max_cap_overrun_kw`; `past_deadline`, `over_max_delay ≤
max_extra_delay_min`; `over_max_reduce ≤ max_extra_reduce_min`; `below_min_power` only if `may_go_below_min_power`;
`enabled: false` → only `ask_owner`.

**Harm ranking (G15).** Each alternative gets an engine-computed `harm_score`: the share of the owner's tolerance it uses,

```
harm_score = Σ over rule_breaks of amount / tolerance(kind)
tolerance: cap_overrun → max_cap_overrun_kw · past_deadline, over_max_delay → max_extra_delay_min ·
           over_max_reduce → max_extra_reduce_min · below_min_power → (min_power_pct − floor), floor = 50 refrigeration else 0
           an authority value of 0 → the engine reference instead (3 kW, 20 min, 15 min)
```

`rank`: `within_authority` first, then `harm_score` ascending, then `cost_delta_usd`, then fewer devices, then `option_id`.
`ask_owner` has `harm_score: null`, `rank: null`. Claude gets the ranked list with context and owner preferences, and may pick
any option: the ranking is the engine's recommendation, not a filter.

**Fallback = `default_option_id`** = rank 1 if it is within authority, else `ask_owner` (nothing extra is applied, which is
physically the overrun). The fallback's Commands are issued **in the same step** the escalation opens (Decisions
`escalation_fallback`), and `active_option_id` = the fallback (`null` for `ask_owner`). The clock keeps its speed; the runtime asks
Claude once, asynchronously, when the escalation opens (later updates are published, not re-asked).

**Update in place.** On each decision tick an active escalation is re-evaluated: `problem` (forecast, excess), options,
projections, ranks and `updated_ts` change; `escalation_id`, `deadline_sim_ts`, `default_option_id` and `active_option_id` do not. The engine never
switches the active option on its own and never reverses executed commands.

- **Obsolete:** the in-rules plan alone (ignoring the active option's rule-breaking commands) now holds the target for that block
  → status `obsolete` (terminal). Already executed commands stay and end at their own planned time.
- Risk returns after an escalation closed → a new escalation for that block.

**Deadline** = `max(ts + 5 min, min(ts + 15 min, block_start − 5 min))`. Still `open` or `awaiting_owner` at the deadline →
`expired_default` (`resolved_by: "default"`; `chosen_option_id` keeps Claude's pick, if any), the fallback stays in force. Decision
ticks fall on 5-minute marks, so the deadline is never after the problem block ends. `obsolete` keeps `resolved_by: null`.

**Resolve** `resolve_escalation(id, option_id, resolved_by, rationale)` (revalidated against the latest state):

- `option_id` not in the current options → `RuleError`. Escalation already closed (`resolved`, `expired_default`, `obsolete`) →
  returned unchanged (the runtime tells Claude what the engine did).
- `claude`: `ask_owner` → `awaiting_owner`, fallback stays. Outside authority (now) → `awaiting_owner` with Claude's pick and
  rationale. Within authority and before the deadline → `resolved`; if it differs from the active option, the next step issues the
  Commands that move devices from the active option to the chosen one (Decisions `escalation_choice`). Whether an option is
  _preferable_ is Claude's judgment (owner preferences, context); the engine only checks what code can check: safe, authorized, timely.
- `owner`: any current option before the deadline → `resolved`, `resolved_by: "owner"` (a Proposal for it expires at the deadline).
- Replay/backtest: nobody answers; the fallback runs and the escalation ends `expired_default`.

`TickState.new_escalations` carries every escalation opened **or changed** in that step (the full object, keyed by id).

## 7. Executor, acks, owner and undo (`engine/kitchen.py`)

- Every Command issued in a step (engine or owner) is in `TickState.new_commands` (delivered in the next `sim_tick`). The engine
  sends nothing itself.
- **Acks** (next HubReport): `ok` + same value → active · `ok` + different `applied_value` → active at the clamped value; its
  effect is re-evaluated at the next decision tick · `ok: false` → not active: `job_running` clears that hold, `already_off` does
  nothing, `unknown_device` → that device is never commanded again this run · no ack → treated as not applied. A rejected
  command is not re-sent in the same block.
- `owner_command(device_id, action, value)` → Command `issued_by: "owner"` plus a Decision `owner_override` (the Command's
  `decision_id`), returned in the next step's `new_commands`. Owners may command any device. The engine leaves that device alone
  for 30 sim min. The runtime calls it on both lanes (`without` first), so both kitchens get the same manual input (fair comparison).
- `undo(decision_id)`: only for an `executed` decision whose action is `reduce` or `delay` (any reason) and whose command is still
  in force (in `active_commands`) → else `RuleError` (API 422). So undo needs no decision history beyond the active commands.
  `reduce` → `restore`; `delay` → `start` if the job is `waiting`, else `delay` value 0 (clears the hold). The reverting Command is
  `issued_by: "owner"` with `decision_id` = the undone decision; that decision becomes `undone`; device protected 30 sim min;
  owed energy already accrued stays in the ledger. `with` lane only.

## 8. Rules check (`engine/rules.py`)

- Validates limits (`set_importance`) and every move. `flexible`: `0 < min_power_pct ≤ 100`, `max_reduce_min > 0`.
  `deferrable`: `max_delay_min ≥ 0`, `must_finish_by` "HH:MM". Refrigeration set to flexible needs `min_power_pct ≥ 50`.
  Refrigeration may be `deferrable` only if its power model is `job` (the ice machine: a hold delays an ice batch, it never
  warms food); a `cycling` refrigeration device (walk-in, reach-in, freezer) set to `deferrable` → `RuleError` (a hold would be 0 %).
- Engine moves: `always_on` never commanded; `reduce` value ≥ `min_power_pct`; holds inside `max_delay_min` and the effective deadline.
- A move that breaks a limit only happens through an Escalation; food safety never.
- Every equipment type's `default_limits` in `equipment_catalog.json` passes these rules (tested).

## 9. Owed-energy ledger (`engine/ledger.py`)

- Each flexible device keeps `owed_kwh`. While reduced: `owed += max(0, expected_kw − actual_kw) × minutes/60`, where
  `expected_kw` = the device's unreduced forecast for that block made when it was reduced. After restore:
  `owed −= max(0, actual_kw − expected_kw) × minutes/60`, never below 0.
- **Live:** the simulation's physics does the catch-up; the ledger measures it. `owed_kwh` per device is in `snapshot()`
  (an estimate). Lanes' daily kWh are compared and reported, not asserted (physics differs between lanes).
- **Replay:** the replay plant puts owed energy back explicitly (section 11), so energy is conserved exactly (±1e-6) and
  `owed_kwh` is 0 at close. That is where the conservation test runs.

## 10. Lane comparison and measured readings

- `compare_lanes(without, with_)` (module-level, exported): `saved_today_usd = without.meter.cost_usd_today −
with_.meter.cost_usd_today`, `peak_avoided_kw = without.meter.month_peak_kw − with_.meter.month_peak_kw`, both peaks copied
  through. The only place lane differences are computed.
- `ingest_reading(reading)`: `with` lane only; applies to the next `step()`. That device uses `reading.power_kw` instead of the
  hub's value, `source: "measured"`, and the engine recomputes `total_kw`. The 30 s staleness rule lives in the runtime. In this
  build every device is simulated (no physical ESP32), so the path exists and is tested but is not used in the demo.

## 11. Replay (`backtest/replay.py`) — the same Kitchen

- Each 15-min ComStock row becomes a HubReport-shaped object: devices from the distribution recipe (DATA_AND_PROOF.md),
  `ts` = row end, `tick_id` = row index; `step(15, report)`. The decider runs on every step.
- The **replay plant** (backtest code, not engine) applies Commands in place of the browser hub, and acks them all `ok`:
  `reduce` caps the device at `value% × rated_kw`; the shortfall goes back into that device in the first later block with room
  (else the last block before close). `delay` / `start` move a job device's energy for that row (dishwasher, ice machine shares)
  whole to the release block.
- Rows are fed one at a time (no peeking). Escalations: fallback only.

## 12. `snapshot()` — pure, per lane

```
{ tick_id, sim_ts, lane, control, peak_mode, config, meter, forecast_kw, forecast_ts,
  devices (latest HubReport state), active_commands, owed_kwh {device_id: kWh},
  open_escalations (open + awaiting_owner), warnings (latest step), recent_decisions (last 20, newest first),
  context, id_counters { d, c, e } }
```

No side effects, no I/O; returns copies. The runtime and AI use the `with` lane.

## 13. `what_if(device_id, action, value, at)`

- `at` = sim timestamp where the hypothetical command starts; must be within `[now, now + 120 min)` → else `RuleError`.
- Runs on a copy of the lane's planning state, applies the hypothetical command at `at`, re-forecasts and returns the Effect
  (section 5 formula). No ids, no Commands, no ledger or escalation change. Unknown device or invalid value → `RuleError`.
- The method is per lane; the AI tool's optional `lane` (default `with`) selects which Kitchen the runtime calls.

## 14. Not in this build (cut, revisit later)

HVAC thermal model and `max_indoor_temp_change_c` · weather in the forecast · learned customer forecast · engine state
(ledger, counters, active commands) surviving a backend restart; a restart is a new run. Month to date is published in
SpacetimeDB `live_tick`; reading it back after a restart belongs to that later feature (section 0).

## 15. Hand-computed tests (`backend/tests/engine/`) — must exist and pass

**Meter:** constant 40 kW for 60 min at 1-min steps → 40 kWh; four blocks of 40 kW; peak 40 kW.
**Demand windows (G36), `demo_tariff_v1`:** a 45 kW block at 16:00 local → `month_peak_kw` 45 and `on_peak_month_peak_kw` 45 ·
a 50 kW block at 15:45 → `month_peak_kw` 50, on-peak unchanged · 20:45 block counts on-peak, 21:00 block does not ·
block 23:45 on 31 July bills to July, 00:00 on 1 August resets both peaks · `cost_usd_today` includes demand added today
(new 45 kW peak over a 40 kW morning peak → +5 × $20 + on-peak increase × $8).
**Minimize target:** previous four Fridays' peaks 38, 41, 39, 40 kW → target 41 kW all day; no history → month peak so far.
**Decider, deferrable:** target 40 kW. Must-run per 15-min block: 30, 38, 40, 36, 28, 22.
Dishwasher 6 kW × 30 min scheduled at block 2 (max delay 60 min).

- Without: 30, 44, 46, 36, 28, 22 → peak 46.
- With: dishwasher moved to blocks 5–6 → 30, 38, 40, 36, 34, 28 → peak 40. Dishwasher energy 3 kWh both ways.
  **Decider, flexible:** target 40. Block load 44 with a flexible HVAC rated 10 kW drawing 10 kW, min 40 %, max reduce 30 min →
  `reduce` value 60 (6 kW, 60 % of rated) → 40 kW; 4 kW × 0.25 h = 1 kWh owed; restore at the 6th decision tick at the latest.
  **Effects add up:** two moves in one replan → `saving_usd` of both sums to the plan's total; `saving_usd = −cost_delta_usd`.
  **Energy conservation (replay):** daily kWh equal to the data (±1e-6); every flexible device's `owed_kwh` is 0 at close.
  **Catalog:** every `default_limits` passes `rules.py` (walk-in cooler flexible ≥ 50 %).
  **compare_lanes:** hand case without cost $61.20, with cost $42.80 → saved $18.40; peaks 46 / 40 → avoided 6.0 kW.
  **Commands out:** a delay decision appears exactly once in `new_commands` for the step it executes; an unchanged plan re-sends nothing.
  **Acks:** clamped ack → active at `applied_value`; `job_running` → hold cleared, not re-sent this block.
  **Escalation:** must-run 44 kW in one block starting in 15 min, cap 40, no in-rules room → escalation opens.
  Authority `max_cap_overrun_kw` = 5 → `accept_overrun` (peak 44) `within_authority`, rank 1, fallback, active at once.
  Authority 3 → it is outside; default = `ask_owner`, nothing applied; nobody resolves by the deadline → `expired_default`.
  Claude choosing `accept_overrun` with authority 3 → `awaiting_owner`. Block starting in 45 min → no escalation yet.
  **Harm ranking:** authority 3 kW / 20 min / 15 min, below-min not allowed. `accept_overrun` 2 kW → 0.667 · `extend_delay_dishwasher`
  past deadline 10 min → 0.5 · `deep_reduce_hvac` 10 pct below min → outside. Ranks 2, 1, 3; fallback `extend_delay_dishwasher`,
  its Commands in the same step's `new_commands` with reason `escalation_fallback`.
  **Update / obsolete:** the same block worsening → same `escalation_id`, new `problem`, `updated_ts`; the in-rules plan alone
  holding it later → `obsolete`, no command reversed. A second risk in the same block after closure → new id.
  **Resolve revalidation:** Claude's within-authority pick, or an owner pick, after the deadline → escalation returned unchanged
  (`expired_default`, `resolved_by: "default"`); unknown option id → `RuleError`.
  **Deadline rule:** opened 12:00 for a 12:15 block → deadline 12:10; for the block in progress → `ts + 5`.
  **Food safety:** no option ever takes a refrigeration device below 50 %.
  **Context:** crowd effect `medium` → multiplier exactly 1.25 on demand_driven forecast only; no context → identical run.
  **Always-on:** no engine Command ever targets an always_on device (assert over a full simulated day).
  **Ids:** both lanes share counters; the same tick stream gives the same ids every run.
  **Undo:** reduce → restore; delay on a waiting job → start; on an idle hold → delay 0; undo of a restore, or of a reduce already
  restored → `RuleError`.
  **Closed hours:** no reduce or hold starts outside `operating_hours`; `cap_unreachable` appears once per block, not every tick.
  **Pure reads:** `snapshot()` and `what_if()` leave the next `step()` output byte-identical; `what_if` outside the horizon → `RuleError`.
  **No-peeking:** history view raises if anything reads a block ending after now; `warm_up` with a block ending after the start
  raises; a full replay day must not raise.
  **Boundary:** the engine imports nothing outside `engine/` and `contracts/`; decider tests run on HubReport fixtures from
  `contracts/fixtures/hub_protocol/` alone.
  **Escalation shape:** alternatives 1–3 plus `ask_owner`, `accept_overrun` always present, the default is one of them, ranks are 1..n.
