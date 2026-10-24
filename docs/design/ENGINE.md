# Design: Engine brain (owner: Kritazya)

Reads the hub, forecasts, decides, executes. Pure Python: no I/O, no wall-clock time, no AI calls.

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

## 4. Decider (`engine/decider.py`) — runs every 5 simulated minutes
```
forecast = forecaster.next_2h()
for each block over target_kw, earliest first:
    excess = block_kw - target_kw
    1. DELAY deferrable jobs that would run in this block
         → to the earliest later block with room, within max_delay_min and before must_finish_by
    2. REDUCE flexible devices in this block, largest first
         → only as much as needed, never below min_power_pct, for at most max_reduce_min;
           schedule catch-up of the owed energy in a block with room
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
- Outside limits: `awaiting_approval`; executed only via `approve()`. Expired → `expired`, re-plan.
- Owner clicks (`owner_command`) always win; the engine leaves that device alone for 30 sim min.
- `undo(decision_id)`: reverts the command and protects the device for 30 sim min.

## 6. Rules check (`engine/rules.py`)
Validates limits (`set_importance`) and every move. A move that breaks a limit is never executed without approval.
Food-safety floor: refrigeration flexible devices can't be set below a safe `min_power_pct` (default 50).

## 7. Hand-computed tests (`backend/tests/engine/`) — must exist and pass
**Meter:** constant 40 kW for 60 min at 1-min steps → 40 kWh; four blocks of 40 kW; peak 40 kW.

**Decider, deferrable:** target 40 kW. Must-run per 15-min block: 30, 38, 40, 36, 28, 22.
Dishwasher 6 kW × 30 min scheduled at block 2 (max delay 60 min).
- Without: 30, 44, 46, 36, 28, 22 → peak 46.
- With: dishwasher moved to blocks 5–6 → 30, 38, 40, 36, 34, 28 → peak 40. Dishwasher energy 3 kWh both ways.

**Decider, flexible:** target 40. Block load 44 with a flexible HVAC at 10 kW, min 40%, max reduce 30 min →
reduce HVAC by only the 4 kW needed, to 6 kW (60%, above the 40% minimum) → 40 kW;
4 kW × 0.25 h = 1 kWh owed, repaid in the next block with room.

**Energy conservation:** daily kWh equal across lanes (±1e-6).
**Always-on:** no Command ever targets an always_on device (assert over a full simulated day).
**No-peeking:** history view raises if anything reads ts ≥ now; a full replay day must not raise.
