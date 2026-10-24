# Design: Engine brain (owner: Kritazya)

Reads the hub, forecasts, decides, executes. Pure Python: no I/O, no wall-clock time, no AI calls, no Convex or
SpacetimeDB. Real ESP32 readings arrive through `ingest_reading()`; commands leave as `TickState.new_commands`.

## 1. Meter (`engine/meter.py`)
- Energy: `energy_kwh += total_kw × minutes / 60`.
- Demand: average kW over each 15-minute block aligned to local :00/:15/:30/:45.
  When a block closes: `month_peak_kw = max(month_peak_kw, block_avg_kw)`. Reset each billing month.
- Cost: energy charges (time-of-use if the tariff has them) + every demand charge the tariff defines
  (many commercial tariffs have more than one, e.g. monthly max and peak-period).

## 2. Forecaster (`engine/forecaster.py`)
- For each 15-min block in the next 2 hours: average total kW of the same weekday + time over the previous 3 weeks.
- Live adjustment: `ratio = actual_last_30min / forecast_last_30min` (clamped 0.5–2.0), applied to the next hour,
  fading back to 1.0 over the second hour.
- Known future load is added on top: queued deferrable jobs at their scheduled times, flexible catch-up energy.
- Only uses history with timestamps before now.

## 3. Target
```
unavoidable_kw = forecast of always_on + flexible-at-minimum load (the lowest the engine could possibly reach)
target_kw      = peak_cap_kw                           if the owner set one
               = max(month_peak_kw, unavoidable_kw)    otherwise   (load below this month's peak is "free")
if unavoidable_kw > peak_cap_kw: emit warning "cap_unreachable" and plan against unavoidable_kw
```

## 4. Decider (`engine/decider.py`) — runs every 5 simulated minutes (live) or every 15-minute step (replay)
```
forecast = forecaster.next_2h()
for each block over target_kw, earliest first:
    excess = block_kw - target_kw
    1. DELAY deferrable jobs that would run in this block
         → to the earliest later block with room, within max_delay_min and before must_finish_by
    2. REDUCE flexible devices in this block, largest first
         → only as much as needed, never below min_power_pct, for at most max_reduce_min;
           add the energy not used to that device's owed_kwh and schedule catch-up in a block with room
    3. never touch always_on
    stop when excess <= 0
if a block is still over target and a move beyond the owner's limits would fix it:
    create Decision(status="awaiting_approval", expires in 10 sim min)
RELEASE: any delayed job whose block now has room (or whose deadline forces it) starts now
```
Order matters: delaying is cheaper than reducing (no comfort impact), so it goes first.

Every move becomes a **Decision** with `effect` computed by re-running the forecast with and without the move:
`peak_before_kw`, `peak_after_kw`, `saving_usd = demand_rate × max(0, peak_before − max(peak_after, month_peak)) + energy cost change`.

## 5. Executor (`engine/kitchen.py`)
- Decisions inside the owner's limits: executed immediately → Command to the hub → `status: executed`.
- Every Command the hub delivers in a step (engine or owner) is returned in `TickState.new_commands`, so the runtime can
  forward it to a real hub. The engine itself never sends anything.
- Outside limits: `awaiting_approval`; executed only via `approve()`. Expired → `expired`, re-plan.
- Owner clicks (`owner_command`) always win; the engine leaves that device alone for 30 sim min.
- `undo(decision_id)`: reverts the command and protects the device for 30 sim min.

## 6. Rules check (`engine/rules.py`)
Validates limits (`set_importance`) and every move. A move that breaks a limit is never executed without approval.
Food-safety floor: refrigeration flexible devices can't be set below a safe `min_power_pct` (default 50).
Every equipment type's `default_limits` in `equipment_catalog.json` must pass these rules (tested).

## 6b. Owed-energy ledger (flexible devices)
- Each flexible device keeps `owed_kwh`. A reduction adds the energy not drawn; catch-up subtracts what is repaid.
- Catch-up is scheduled by the decider into blocks with room under the target; it never creates a new peak if avoidable.
- `owed_kwh` must be 0 by the end of the operating day (close time). Physics models (cycling, thermal) may shape *when*
  power is drawn, but the ledger is what guarantees conservation.

## 6c. Lane comparison and measured readings
- `compare_lanes(without, with_)` (module-level, exported): `saved_today_usd = without.meter.cost_usd_today −
  with_.meter.cost_usd_today`, `peak_avoided_kw = without.meter.month_peak_kw − with_.meter.month_peak_kw`, both peaks
  copied through. The only place lane differences are computed.
- `ingest_reading(reading)`: applies to the next `step()` only. That device uses `reading.power_kw` instead of its model and
  is marked `source: "measured"`. The runtime passes the latest fresh reading before every step; a step with no reading
  uses the model again (`simulated`). The 30 s staleness rule lives in the runtime, not the engine. `with` lane only.

## 7. Hand-computed tests (`backend/tests/engine/`) — must exist and pass
**Meter:** constant 40 kW for 60 min at 1-min steps → 40 kWh; four blocks of 40 kW; peak 40 kW.

**Decider, deferrable:** target 40 kW. Must-run per 15-min block: 30, 38, 40, 36, 28, 22.
Dishwasher 6 kW × 30 min scheduled at block 2 (max delay 60 min).
- Without: 30, 44, 46, 36, 28, 22 → peak 46.
- With: dishwasher moved to blocks 5–6 → 30, 38, 40, 36, 34, 28 → peak 40. Dishwasher energy 3 kWh both ways.

**Decider, flexible:** target 40. Block load 44 with a flexible HVAC at 10 kW, min 40%, max reduce 30 min →
reduce HVAC by only the 4 kW needed, to 6 kW (60%, above the 40% minimum) → 40 kW;
4 kW × 0.25 h = 1 kWh owed, repaid in the next block with room.

**Energy conservation:** daily kWh equal across lanes (±1e-6); every flexible device's `owed_kwh` is 0 at close.
**Catalog:** every `default_limits` passes `rules.py` (walk-in cooler flexible ≥ 50%).
**compare_lanes:** hand case without cost $61.20, with cost $42.80 → saved $18.40; peaks 46 / 40 → avoided 6.0 kW.
**Commands out:** a delay decision appears exactly once in `new_commands` for the step it executes.
**Always-on:** no Command ever targets an always_on device (assert over a full simulated day).
**No-peeking:** history view raises if anything reads ts ≥ now; a full replay day must not raise.
