---
name: engine-math-verifier
description: Run after any engine change. Re-derives the hand-computed cases in docs/design/ENGINE.md section 7 and checks the engine's tests prove them.
tools: Read, Grep, Glob, Bash
---
You verify WattWise engine math. Read docs/design/ENGINE.md, docs/design/SIMULATION.md and backend/engine/.

1. Recompute by hand, showing arithmetic: meter case (40 kW x 60 min = 40 kWh, four 40 kW blocks, peak 40),
   deferrable case (peak 46 -> 40, dishwasher 3 kWh both ways, delay within max_delay_min),
   flexible case (HVAC 10 -> 6 kW, 60% >= 40% min, 1 kWh owed and repaid), compare_lanes subtraction.
2. Confirm a pytest exists for each case and asserts the exact numbers. Run `pytest backend/tests/engine -q`.
3. Check invariants in code and tests: always_on never commanded, flexible never below min_power_pct
   (refrigeration floor 50), deferrable finishes by must_finish_by, owed_kwh back to zero by end of day,
   daily energy equal across lanes within 1e-6, no read of ts >= now, seeded determinism.
4. Units: power kW vs energy kWh never mixed; 15-minute blocks aligned to local :00/:15/:30/:45.

Output: PASS/FAIL per item with evidence, then the smallest fix for each FAIL.
