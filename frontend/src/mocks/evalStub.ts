// STUB: illustrative placeholder eval artifact (docs/Claude_EVAL.md §11). No eval has been run; nothing here is a result.
// Generated once from a throwaway script; replace with the eval runner's artifact when Kritazya publishes one.
import type { EvalArtifact } from "@/types";

export const EVAL_STUB: EvalArtifact = {
  "run_id": "eval_stub_0001",
  "source": "illustrative_stub",
  "generated_at": "2026-10-24T00:00:00Z",
  "provenance": {
    "engine_version": "none (no eval run yet)",
    "plant": "none (placeholder values)",
    "tariff_id": "demo_tariff_v1",
    "tariff_label": "illustrative",
    "seeds": [
      17
    ],
    "note": "Hand-made placeholder so the Evaluation Lab can be built. No eval has been run; every value is illustrative."
  },
  "scenarios": [
    {
      "scenario_id": "hot_friday_rush",
      "name": "Hot Friday dinner rush",
      "summary": "Hot evening, Giants game nearby, dinner rush from 18:30.",
      "weather_label": "hot",
      "traffic_label": "dinner rush",
      "outdoor_max_c": 33,
      "peak_cap_kw": 40,
      "split": "dev"
    },
    {
      "scenario_id": "mild_day",
      "name": "Mild weeknight",
      "summary": "Mild evening, normal traffic.",
      "weather_label": "mild",
      "traffic_label": "normal",
      "outdoor_max_c": 21,
      "peak_cap_kw": 40,
      "split": "dev"
    },
    {
      "scenario_id": "extreme_heat",
      "name": "Extreme heat",
      "summary": "Heat wave evening with a dinner rush; HVAC near capacity.",
      "weather_label": "extreme heat",
      "traffic_label": "dinner rush",
      "outdoor_max_c": 39,
      "peak_cap_kw": 40,
      "split": "held_out"
    }
  ],
  "strategies": [
    {
      "strategy_id": "unoptimized",
      "name": "No control",
      "kind": "baseline",
      "deployable": true,
      "summary": "Appliances run as usual; no load shifting."
    },
    {
      "strategy_id": "conservative_hvac",
      "name": "Conservative HVAC",
      "kind": "hvac_only",
      "deployable": true,
      "summary": "HVAC reduced at most 10% of rated power, within comfort limits."
    },
    {
      "strategy_id": "balanced_hvac",
      "name": "Balanced HVAC",
      "kind": "hvac_only",
      "deployable": true,
      "summary": "HVAC reduced at most 25% of rated power, within comfort limits."
    },
    {
      "strategy_id": "aggressive_hvac",
      "name": "Aggressive HVAC",
      "kind": "hvac_only",
      "deployable": true,
      "summary": "HVAC reduced up to 40% of rated power; violations are recorded, not hidden."
    },
    {
      "strategy_id": "wattwise",
      "name": "Full WattWise",
      "kind": "wattwise",
      "deployable": true,
      "summary": "Defers jobs first, then trims flexible loads within the owner's rules, and repays owed energy."
    }
  ],
  "hard_constraints": [
    {
      "constraint_id": "food_safety_floor",
      "label": "Refrigeration never below 50%"
    },
    {
      "constraint_id": "always_on_untouched",
      "label": "Always-on devices never commanded"
    },
    {
      "constraint_id": "job_deadlines",
      "label": "Deferrable jobs finish by their deadline"
    },
    {
      "constraint_id": "owner_limits",
      "label": "Owner limits respected (min power, max reduce)"
    },
    {
      "constraint_id": "claude_authority",
      "label": "No action outside Claude's authority"
    }
  ],
  "results": [
    {
      "scenario_id": "hot_friday_rush",
      "strategy_id": "unoptimized",
      "verdict": "pass",
      "bill": {
        "energy_usd": 60.9,
        "demand_usd": 1344,
        "total_usd": 1404.9
      },
      "savings_usd": null,
      "peak_demand_kw": 48,
      "peak_avoided_kw": null,
      "comfort": {
        "max_indoor_temp_c": 24.8,
        "degree_minutes_above": 0,
        "minutes_outside_band_min": 0
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 0,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 45
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 47
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 48
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 46
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 44
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 36
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 33
        }
      ],
      "trace": null
    },
    {
      "scenario_id": "hot_friday_rush",
      "strategy_id": "conservative_hvac",
      "verdict": "pass",
      "bill": {
        "energy_usd": 59.05,
        "demand_usd": 1288,
        "total_usd": 1347.05
      },
      "savings_usd": 57.85,
      "peak_demand_kw": 46,
      "peak_avoided_kw": 2,
      "comfort": {
        "max_indoor_temp_c": 25.5,
        "degree_minutes_above": 27.5,
        "minutes_outside_band_min": 50
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 6,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 43
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 45
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 46
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 44
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 36.6
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 36
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 33
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:45:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 90%",
        "reason": "Fixed 10% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 48,
        "peak_after_kw": 46
      }
    },
    {
      "scenario_id": "hot_friday_rush",
      "strategy_id": "balanced_hvac",
      "verdict": "pass",
      "bill": {
        "energy_usd": 57.44,
        "demand_usd": 1232,
        "total_usd": 1289.44
      },
      "savings_usd": 115.46,
      "peak_demand_kw": 44,
      "peak_avoided_kw": 4,
      "comfort": {
        "max_indoor_temp_c": 26.6,
        "degree_minutes_above": 88,
        "minutes_outside_band_min": 94
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 9,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 36.2
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 41
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 43
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 44
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 36.4
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 36
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 36
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 33
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:45:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 75%",
        "reason": "Fixed 25% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 48,
        "peak_after_kw": 44
      }
    },
    {
      "scenario_id": "hot_friday_rush",
      "strategy_id": "aggressive_hvac",
      "verdict": "fail",
      "bill": {
        "energy_usd": 55.36,
        "demand_usd": 1148,
        "total_usd": 1203.36
      },
      "savings_usd": 201.54,
      "peak_demand_kw": 41,
      "peak_avoided_kw": 7,
      "comfort": {
        "max_indoor_temp_c": 27.6,
        "degree_minutes_above": 143,
        "minutes_outside_band_min": 134
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 2
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 12,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 35.3
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 35.9
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 41
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 35.9
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 35.5
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 35.1
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 36
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 33
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:45:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 60%",
        "reason": "Fixed 40% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 48,
        "peak_after_kw": 41
      }
    },
    {
      "scenario_id": "hot_friday_rush",
      "strategy_id": "wattwise",
      "verdict": "pass",
      "bill": {
        "energy_usd": 59.18,
        "demand_usd": 1103.2,
        "total_usd": 1162.38
      },
      "savings_usd": 242.52,
      "peak_demand_kw": 39.4,
      "peak_avoided_kw": 8.6,
      "comfort": {
        "max_indoor_temp_c": 26.6,
        "degree_minutes_above": 88,
        "minutes_outside_band_min": 94
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 9,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 38.4
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 38.4
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 38.4
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 38.4
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 38.4
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 38.4
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 38.4
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:15:00.000Z",
        "device_name": "Dishwasher",
        "action": "Delay 30 min",
        "reason": "Its cycle would land in the busiest dinner block; it still finishes before 19:30.",
        "peak_before_kw": 48,
        "peak_after_kw": 39.4
      }
    },
    {
      "scenario_id": "mild_day",
      "strategy_id": "unoptimized",
      "verdict": "pass",
      "bill": {
        "energy_usd": 53.3,
        "demand_usd": 1204,
        "total_usd": 1257.3
      },
      "savings_usd": null,
      "peak_demand_kw": 43,
      "peak_avoided_kw": null,
      "comfort": {
        "max_indoor_temp_c": 24.2,
        "degree_minutes_above": 0,
        "minutes_outside_band_min": 0
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 0,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 29
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 32
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 43
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 41
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 33
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 31
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 28
        }
      ],
      "trace": null
    },
    {
      "scenario_id": "mild_day",
      "strategy_id": "conservative_hvac",
      "verdict": "pass",
      "bill": {
        "energy_usd": 52.35,
        "demand_usd": 1148,
        "total_usd": 1200.35
      },
      "savings_usd": 56.95,
      "peak_demand_kw": 41,
      "peak_avoided_kw": 2,
      "comfort": {
        "max_indoor_temp_c": 24.5,
        "degree_minutes_above": 0,
        "minutes_outside_band_min": 0
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 6,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 29
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 32
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 41
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 33
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 31
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 28
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:45:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 90%",
        "reason": "Fixed 10% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 43,
        "peak_after_kw": 41
      }
    },
    {
      "scenario_id": "mild_day",
      "strategy_id": "balanced_hvac",
      "verdict": "pass",
      "bill": {
        "energy_usd": 51.55,
        "demand_usd": 1092,
        "total_usd": 1143.55
      },
      "savings_usd": 113.75,
      "peak_demand_kw": 39,
      "peak_avoided_kw": 4,
      "comfort": {
        "max_indoor_temp_c": 24.8,
        "degree_minutes_above": 0,
        "minutes_outside_band_min": 0
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 9,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 29
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 32
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 36.4
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 36.2
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 33
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 31
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 28
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:45:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 75%",
        "reason": "Fixed 25% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 43,
        "peak_after_kw": 39
      }
    },
    {
      "scenario_id": "mild_day",
      "strategy_id": "aggressive_hvac",
      "verdict": "pass",
      "bill": {
        "energy_usd": 50.78,
        "demand_usd": 1036,
        "total_usd": 1086.78
      },
      "savings_usd": 170.52,
      "peak_demand_kw": 37,
      "peak_avoided_kw": 6,
      "comfort": {
        "max_indoor_temp_c": 25.1,
        "degree_minutes_above": 5.5,
        "minutes_outside_band_min": 34
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 12,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 29
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 32
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 35.5
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 35.9
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 36.1
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 35.7
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 35.3
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 33
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 31
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 28
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:00:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 60%",
        "reason": "Fixed 40% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 43,
        "peak_after_kw": 37
      }
    },
    {
      "scenario_id": "mild_day",
      "strategy_id": "wattwise",
      "verdict": "pass",
      "bill": {
        "energy_usd": 53.29,
        "demand_usd": 1103.2,
        "total_usd": 1156.49
      },
      "savings_usd": 100.81,
      "peak_demand_kw": 39.4,
      "peak_avoided_kw": 3.6,
      "comfort": {
        "max_indoor_temp_c": 24.8,
        "degree_minutes_above": 0,
        "minutes_outside_band_min": 0
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 9,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 29
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 32
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 34
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 39.4
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 35
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 33
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 31
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 30
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 36.4
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:15:00.000Z",
        "device_name": "Dishwasher",
        "action": "Delay 30 min",
        "reason": "Its cycle would land in the busiest dinner block; it still finishes before 19:30.",
        "peak_before_kw": 43,
        "peak_after_kw": 39.4
      }
    },
    {
      "scenario_id": "extreme_heat",
      "strategy_id": "unoptimized",
      "verdict": "pass",
      "bill": {
        "energy_usd": 66.97,
        "demand_usd": 1456,
        "total_usd": 1522.97
      },
      "savings_usd": null,
      "peak_demand_kw": 52,
      "peak_avoided_kw": null,
      "comfort": {
        "max_indoor_temp_c": 25.3,
        "degree_minutes_above": 16.5,
        "minutes_outside_band_min": 42
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 0,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 41
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 43
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 46
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 49
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 51
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 52
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 50
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 48
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 46
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 44
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 37
        }
      ],
      "trace": null
    },
    {
      "scenario_id": "extreme_heat",
      "strategy_id": "conservative_hvac",
      "verdict": "pass",
      "bill": {
        "energy_usd": 64.18,
        "demand_usd": 1400,
        "total_usd": 1464.18
      },
      "savings_usd": 58.79,
      "peak_demand_kw": 50,
      "peak_avoided_kw": 2,
      "comfort": {
        "max_indoor_temp_c": 26.4,
        "degree_minutes_above": 77,
        "minutes_outside_band_min": 86
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 6,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 36.6
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 41
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 44
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 47
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 49
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 50
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 48
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 46
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 44
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 37
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:45:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 90%",
        "reason": "Fixed 10% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 52,
        "peak_after_kw": 50
      }
    },
    {
      "scenario_id": "extreme_heat",
      "strategy_id": "balanced_hvac",
      "verdict": "pass",
      "bill": {
        "energy_usd": 61.73,
        "demand_usd": 1344,
        "total_usd": 1405.73
      },
      "savings_usd": 117.24,
      "peak_demand_kw": 48,
      "peak_avoided_kw": 4,
      "comfort": {
        "max_indoor_temp_c": 28.1,
        "degree_minutes_above": 170.5,
        "minutes_outside_band_min": 154
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 9,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 36
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 36.2
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 45
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 47
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 48
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 46
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 44
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 40
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 38
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 36.4
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 36.2
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 37
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:45:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 75%",
        "reason": "Fixed 25% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 52,
        "peak_after_kw": 48
      }
    },
    {
      "scenario_id": "extreme_heat",
      "strategy_id": "aggressive_hvac",
      "verdict": "fail",
      "bill": {
        "energy_usd": 58.51,
        "demand_usd": 1260,
        "total_usd": 1318.51
      },
      "savings_usd": 204.46,
      "peak_demand_kw": 45,
      "peak_avoided_kw": 7,
      "comfort": {
        "max_indoor_temp_c": 29.8,
        "degree_minutes_above": 264,
        "minutes_outside_band_min": 222
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 4
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 12,
        "escalations": 0,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 35.1
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 35.3
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 35.7
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 36.1
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 44
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 45
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 43
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 41
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 39
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 37
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 35.9
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 35.5
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 35.3
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 37
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:45:00.000Z",
        "device_name": "HVAC 1",
        "action": "Turn down to 60%",
        "reason": "Fixed 40% HVAC reduction while demand is near the cap.",
        "peak_before_kw": 52,
        "peak_after_kw": 45
      }
    },
    {
      "scenario_id": "extreme_heat",
      "strategy_id": "wattwise",
      "verdict": "pass",
      "bill": {
        "energy_usd": 63.84,
        "demand_usd": 1187.2,
        "total_usd": 1251.04
      },
      "savings_usd": 271.93,
      "peak_demand_kw": 42.4,
      "peak_avoided_kw": 9.6,
      "comfort": {
        "max_indoor_temp_c": 28.1,
        "degree_minutes_above": 170.5,
        "minutes_outside_band_min": 154
      },
      "violations": [
        {
          "constraint_id": "food_safety_floor",
          "count": 0
        },
        {
          "constraint_id": "always_on_untouched",
          "count": 0
        },
        {
          "constraint_id": "job_deadlines",
          "count": 0
        },
        {
          "constraint_id": "owner_limits",
          "count": 0
        },
        {
          "constraint_id": "claude_authority",
          "count": 0
        }
      ],
      "operations": {
        "commands": 9,
        "escalations": 1,
        "unmet_kwh": 0
      },
      "demand_blocks": [
        {
          "block_start_ts": "2026-07-18T00:00:00.000Z",
          "demand_kw": 41.4
        },
        {
          "block_start_ts": "2026-07-18T00:15:00.000Z",
          "demand_kw": 41.4
        },
        {
          "block_start_ts": "2026-07-18T00:30:00.000Z",
          "demand_kw": 41.4
        },
        {
          "block_start_ts": "2026-07-18T00:45:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T01:00:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T01:15:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T01:30:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T01:45:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T02:00:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T02:15:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T02:30:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T02:45:00.000Z",
          "demand_kw": 42.4
        },
        {
          "block_start_ts": "2026-07-18T03:00:00.000Z",
          "demand_kw": 42
        },
        {
          "block_start_ts": "2026-07-18T03:15:00.000Z",
          "demand_kw": 41.4
        },
        {
          "block_start_ts": "2026-07-18T03:30:00.000Z",
          "demand_kw": 41.4
        },
        {
          "block_start_ts": "2026-07-18T03:45:00.000Z",
          "demand_kw": 41.4
        }
      ],
      "trace": {
        "ts": "2026-07-18T01:15:00.000Z",
        "device_name": "Dishwasher",
        "action": "Delay 30 min",
        "reason": "Its cycle would land in the busiest dinner block; it still finishes before 19:30.",
        "peak_before_kw": 52,
        "peak_after_kw": 42.4
      }
    }
  ]
};
