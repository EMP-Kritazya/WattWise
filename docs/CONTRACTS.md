# Contracts

The single source of truth for every shape shared between the Frontend (UI + simulation + hub), the API/runtime/AI and the Engine.

- JSON is snake_case. Units in field names. Timestamps ISO 8601 with timezone.
- Backend: Pydantic models in `backend/contracts/`. Frontend: types generated from OpenAPI + `contracts/ws_messages.schema.json`
  - SpacetimeDB generated bindings + Convex generated types. Nothing hand written.
- SpacetimeDB rows and Convex documents carry the same snake_case fields as the shapes below.
- Change this file in the same commit as any shape change, and tell the team (use the `contract-sync` subagent),
  then regenerate `contracts/fixtures/` with the `fixture-builder` subagent.
- Engine behaviour behind these shapes: `docs/design/ENGINE.md`. Open points: `Main_Gaps.md`.

Contents: 1 Shared shapes · 2 S1 REST + WebSocket · 3 S2 Engine facade · 4 AI tools · 5 S3 SpacetimeDB ·
6 S4 Convex · 7 S5 Agent messages · 8 S6 Hub protocol (browser hub ↔ FastAPI) · 9 S7 Appliance interface (inside the browser)

---

## 1. Shared shapes

### Importance

`"always_on" | "flexible" | "deferrable"`

### EquipmentType (catalog entry, read-only, from `backend/data/equipment_catalog.json`)

```json
{
  "type_id": "dishwasher",
  "name": "Dishwasher",
  "category": "water_heating",
  "default_importance": "deferrable",
  "rated_kw": 6.0,
  "power_model": "job",
  "params": { "cycle_min": 30 },
  "default_limits": { "max_delay_min": 60, "must_finish_by": "15:30" },
  "source_note": "FSTC / ENERGY STAR"
}
```

`default_limits`: the limits a new unit of this type starts with. They must pass `rules.py`
(a refrigeration device set to flexible needs `min_power_pct` ≥ 50).
`category`: cooling | refrigeration | cooking | water_heating | lighting | other.
`power_model`: fixed | cycling | thermal | demand_driven | job (see design/SIMULATION.md).
`params` keys per power model: fixed `{}` · cycling `{ duty_idle_pct, duty_busy_pct }` · thermal `{ setpoint_c }` ·
demand_driven `{ idle_kw, kw_per_order }` · job `{ cycle_min }`. Minimum power lives only in `default_limits.min_power_pct`.

### ImportanceLimits (depends on importance)

```json
{
  "always_on": {},
  "flexible": { "min_power_pct": 40, "max_reduce_min": 30 },
  "deferrable": { "max_delay_min": 60, "must_finish_by": "15:30" }
}
```

Examples only. Real starting values come from each EquipmentType's `default_limits`.
Food safety floor: refrigeration devices set to flexible must keep `min_power_pct` ≥ 50.

### KitchenConfig (built in the UI, sent to the API, passed to the engine)

```json
{
  "name": "Demo Café",
  "equipment": [
    {
      "type_id": "hvac",
      "count": 2,
      "importance": "flexible",
      "limits": { "min_power_pct": 40, "max_reduce_min": 30 }
    },
    {
      "type_id": "walk_in_cooler",
      "count": 1,
      "importance": "flexible",
      "limits": { "min_power_pct": 50, "max_reduce_min": 30 }
    },
    {
      "type_id": "reach_in_fridge",
      "count": 1,
      "importance": "always_on",
      "limits": {}
    },
    {
      "type_id": "freezer",
      "count": 1,
      "importance": "always_on",
      "limits": {}
    },
    {
      "type_id": "ice_machine",
      "count": 1,
      "importance": "deferrable",
      "limits": { "max_delay_min": 60, "must_finish_by": "22:00" }
    },
    { "type_id": "fryer", "count": 1, "importance": "always_on", "limits": {} },
    { "type_id": "oven", "count": 1, "importance": "always_on", "limits": {} },
    { "type_id": "grill", "count": 1, "importance": "always_on", "limits": {} },
    {
      "type_id": "dishwasher",
      "count": 1,
      "importance": "deferrable",
      "limits": { "max_delay_min": 60, "must_finish_by": "19:30" }
    },
    {
      "type_id": "water_heater",
      "count": 1,
      "importance": "flexible",
      "limits": { "min_power_pct": 40, "max_reduce_min": 30 }
    },
    { "type_id": "lights", "count": 1, "importance": "always_on", "limits": {} }
  ],
  "peak_mode": "cap",
  "peak_cap_kw": 40.0,
  "operating_hours": { "open": "10:00", "close": "22:00" },
  "location": { "lat": 37.8, "lon": -122.44, "label": "Marina, San Francisco" },
  "owner_preferences": "Keep the dining room comfortable during dinner service.",
  "authority": "<ClaudeAuthority>",
  "tariff_id": "demo_tariff_v1",
  "run_days": 1,
  "seed": 42
}
```

This is the **Demo Café** config: all 11 catalog types (hvac × 2, every other type × 1) with catalog default limits, except
the dishwasher's `must_finish_by` moved to 19:30 so it matters during the 17:30–19:30 demo (fake data, but a hard owner limit for
the engine). Count 0 = not in this kitchen. Each unit becomes a Device with id `<type_id>_<n>` (e.g. `hvac_1`, `hvac_2`); the same
roster is sent to the simulation (`sim_build.devices`) and built into both engine lanes.
`peak_mode`: `minimize` (no fixed number; `peak_cap_kw` is null. The engine holds, as a hard limit for the local day, the highest
15-min peak of the 4 previous same weekdays, from history) |
`cap` (plan against the owner's `peak_cap_kw`; an unavoidable overrun opens an escalation. Claude may accept only
within its authority; if no option is authorized, the engine keeps the in-rules plan with accept_overrun as fallback).
`run_days`: how many service days one run lasts (integer ≥ 1, default 1; Builder offers 1 · 3 · 7 · 14). Day 1 starts at
`start_sim_ts`, every later day at `operating_hours.open`; the run pauses with `paused_reason: "run_complete"` after the last
day's close, and `POST /api/sim/control {action: "next_day"}` adds one more day (Day lifecycle, section 8).

### Tariff (passed to the engine as `Kitchen(config, tariff, ...)`; served by `GET /api/kitchen`)

```json
{
  "tariff_id": "demo_tariff_v1",
  "name": "WattWise demo commercial rate",
  "label": "illustrative",
  "currency": "USD",
  "timezone": "America/Los_Angeles",
  "energy": [
    {
      "name": "off_peak",
      "start": "00:00",
      "end": "16:00",
      "usd_per_kwh": 0.22
    },
    { "name": "peak", "start": "16:00", "end": "21:00", "usd_per_kwh": 0.38 },
    {
      "name": "off_peak",
      "start": "21:00",
      "end": "24:00",
      "usd_per_kwh": 0.22
    }
  ],
  "demand": [
    { "name": "max_demand", "windows": null, "months": null, "days": "all", "usd_per_kw": 20.0 },
    {
      "name": "peak_demand",
      "windows": [{ "start": "16:00", "end": "21:00" }],
      "months": null,
      "days": "all",
      "usd_per_kw": 8.0
    }
  ],
  "fixed_charges": []
}
```

Demo: one made-up tariff, identical in every run (`label: "illustrative"`). Real: an OpenEI URDB rate (`label: "urdb"`, the main
one is PG&E B-19, see below), same shape, converted by `backend/data/tariff_urdb.py`. The owner's bill always uses the tariff;
Context grid prices are a market signal only. All times and months are local (`timezone`); billing month = local calendar month.

**Seasons, days and windows (2026-10-24, for B-19).** Every energy period and demand charge may carry:
`months`: list of local months 1–12 it applies in (`null` = every month) · `days`: `"all"` (default) | `"weekdays"` | `"weekends"`
(Mon–Fri vs Sat–Sun; holidays are not modelled) · energy `start`/`end` and window `start`/`end` "HH:MM" (`end` may be "24:00";
`[start, end)`; `end` < `start` wraps past midnight, e.g. 21:00–09:00; the day type and month are those of the minute itself).
- **Energy:** for every local minute of the year **exactly one** energy period matches (month, day type, time); the tariff is
  rejected otherwise (`ValueError` at `Kitchen(...)` / loader).
- **Demand:** a charge **applies in a month** if `months` is null or contains it. `windows: null` = every hour; otherwise a list of
  `{start, end}` and a 15-min block counts when its local start is in **any** window (one charge, one peak: B-19 summer part-peak
  is one charge with two windows, 14:00–16:00 and 21:00–23:00) and its day type matches. Each applicable charge bills
  `usd_per_kw × the highest closed 15-min block average kW that counts for it this billing month`. Any number of charges.
- **`fixed_charges`:** `[{ "name": "customer_charge", "usd": 11.37, "per": "day" | "month" }]` (default `[]`), billed to both
  lanes alike; included in Bill `fixed_usd` and the Meter costs.
- Not modelled (documented exclusions): PG&E Peak Day Pricing event days, demand ratchets, tiered energy, power-factor charges.

PG&E B-19 (URDB `69de8cdb02f684104e01267d`) in this shape: `max_demand` all months, all hours, $37.37/kW · `peak_demand_winter`
months 1–5, 10–12, 16:00–21:00, $2.31/kW · `peak_demand_summer` months 6–9, 16:00–21:00, $46.16/kW · `part_peak_demand_summer`
months 6–9, windows 14:00–16:00 + 21:00–23:00, $10.52/kW · six energy periods by season (incl. spring super-off-peak 09:00–14:00,
months 3–5) · a daily fixed charge. Values come from the URDB record unchanged (golden rule 6).

### WarmUpHistory (built by `backend/data/warmup.py` from NREL ComStock, or the fixture history until then; passed to `Kitchen.warm_up(history)`)

```json
{
  "source": "nrel_comstock",
  "label": "calibrated_model",
  "dataset_id": "<ComStock release / building id>",
  "scale": 0.42,
  "day_offset": -1098,
  "start": "2026-06-19T07:00:00Z",
  "end": "2026-07-18T00:30:00Z",
  "blocks": [
    {
      "block_start": "2026-06-19T07:00:00Z",
      "device_id": "hvac_1",
      "avg_kw": 4.1
    }
  ],
  "month_to_date": null
}
```

`blocks`: 15-min average kW per device of this kitchen for the 4 weeks before `end` (= the run's `start_sim_ts`), from the
ComStock restaurant scaled to the kitchen (`scale`) and spread onto devices by the distribution recipe (DATA_AND_PROOF.md).
`day_offset`: whole days added to the dataset dates so weekdays line up with the sim calendar. Every block ends at or before `end`.
`month_to_date`: null (the engine meters the history blocks of the current month itself) or
`{ "month": "2026-07", "month_peak_kw": 44.2, "on_peak_month_peak_kw": 41.0, "energy_kwh_month": 7400.0, "cost_usd_month": 2650.0,
"demand_peaks": [{ "name": "max_demand", "peak_kw": 44.2, "usd_per_kw": 37.37, "cost_usd": 1651.75 }] }` (`demand_peaks` = the Meter's, one per
applicable charge, so every seasonal peak is restored; `live_tick.demand_peaks_json` carries it)
(restored from the SpacetimeDB `live_tick` row of the same month).
`source` / `label`: `nrel_comstock` / `calibrated_model` (real build) or `fixture_synthetic` / `simulated` (the fake 2-month history in
`contracts/fixtures/history/`, used until the ComStock extract exists). `blocks` may start earlier than 4 weeks before `end`
(the fixture covers about 2 months so the previous month can be billed); the forecaster and `minimize` target use only the last
4 weeks, and the engine meters only the current month's blocks into month to date.

### Warning (engine or runtime; TickState `warnings` and the ws `warning` message)

```json
{
  "code": "cap_unreachable",
  "message": "text",
  "data": { "unavoidable_kw": 44.0, "peak_cap_kw": 40.0, "target_kw": 40.0 }
}
```

Codes and `data` in section 2 (ws `warning`). The engine emits only `cap_unreachable`; the others come from the runtime.

### ClaudeAuthority (owner-set bounds for resolving escalations without asking)

```json
{
  "enabled": true,
  "max_cap_overrun_kw": 3.0,
  "max_extra_delay_min": 20,
  "max_extra_reduce_min": 15,
  "may_go_below_min_power": false
}
```

Engine marks each escalation option `within_authority` against these. The refrigeration food-safety floor (50 %) is never
crossable, whatever the authority says. `enabled: false` → Claude chooses nothing and the engine's default applies.
**Full authority (Oct 24):** the Builder no longer shows these settings; it always sends
`{ "enabled": true, "max_cap_overrun_kw": 1000, "max_extra_delay_min": 0, "max_extra_reduce_min": 1440, "may_go_below_min_power": false }`
(the peak may run over the cap and flexible units stay reduced longer, but deadlines and minimum power stay hard). Claude is
offered all ranked options with their `within_authority` flags, so escalations never wait for the owner and never pause the clock.

### Device (live state of one unit)

```json
{
  "device_id": "hvac_1",
  "type_id": "hvac",
  "name": "HVAC 1",
  "importance": "flexible",
  "state": "reduced",
  "power_kw": 4.8,
  "rated_kw": 12.0,
  "power_pct": 40,
  "source": "simulated",
  "physical": { "indoor_temp_c": 22.4 }
}
```

`state`: off | on | reduced | waiting (deferred job queued) | running_job.
`source`: simulated | measured. Only a device fed by a real ESP32 reading (`ingest_reading`) is measured.
`power_pct` = round(100 × power_kw / rated_kw), set by the hub.
`physical` (optional, from the simulation, by power model): `indoor_temp_c` (thermal) · `box_temp_c` (cycling) ·
`dirty_racks`, `ice_level_pct`, `job_remaining_min` (job) · `orders_in_progress` (demand_driven). Unknown keys are ignored.

### HubReport (the hub's current state of one lane, sent every tick; the engine's only view of the kitchen)

```json
{
  "hub_id": "sim_hub",
  "lane": "with",
  "tick_id": 1095,
  "ts": "2026-07-17T19:15:00Z",
  "total_kw": 38.2,
  "customers_per_hour": 64,
  "devices": ["<Device>"],
  "acks": ["<CommandAck>"],
  "source": "simulated"
}
```

`acks`: one CommandAck for every Command of this lane delivered in this tick (empty otherwise), so the engine receives them.
`ts` = end of the simulated minute just stepped. `total_kw` = sum of `devices[].power_kw` (hub-computed, exact).
Top level `source`: simulated | mixed (at least one device is measured; set by the runtime after merging ESP32 readings).

### Reading (real ESP32 → Convex → runtime → engine)

```json
{
  "hub_id": "esp32_1",
  "channel": 0,
  "device_id": "dishwasher_1",
  "ts": "...",
  "raw_w": 6.2,
  "scale": 1000,
  "power_kw": 6.2
}
```

`power_kw = raw_w × scale / 1000`. Bench loads draw watts, so each channel declares a `scale` in Convex
`device_map`; the UI labels such a device "measured (scaled)". Readings feed the `with` lane only.

### Command (engine → runtime → `sim_tick` → hub → appliance)

```json
{
  "command_id": "c_0192",
  "lane": "with",
  "ts": "...",
  "device_id": "dishwasher_1",
  "action": "delay",
  "value": 20,
  "decision_id": "d_0041",
  "issued_by": "engine"
}
```

`action`: on | off | start | delay (value = minutes) | reduce (value = power %) | restore.
`reduce`: `value` = % of the device's `rated_kw`; the device draws at most `value% × rated_kw` (a device already below that is
unaffected). `min_power_pct` uses the same base.
`delay`: `value` minutes from when the hub applies it; on an idle job device it holds the next job (`waiting`); on a waiting job
it replaces the hold; `value: 0` clears the hold. The hub releases the job by itself when the hold ends. Idle job devices report `state: "off"`.
`issued_by`: engine | owner (manual click, or an owner confirmed action from the UI or ASI:One).
`decision_id`: the engine Decision; for a manual owner command, its `owner_override` Decision; for an undo, the undone Decision.

### CommandAck (hub → runtime → engine, inside each lane's HubReport)

```json
{
  "command_id": "c_0192",
  "lane": "with",
  "ok": true,
  "applied_value": 20,
  "reason": null
}
```

`ok: true` + `applied_value == value` → applied. `ok: true` + different `applied_value` → applied but clamped to a physical
limit (`reason: out_of_range`). `ok: false` → not applied (`reason`: job_running | already_off | unknown_device).
`reason` is null when applied unchanged. The next HubReport shows the real state.

### Decision (engine output)

```json
{
  "decision_id": "d_0041",
  "ts": "...",
  "device_id": "dishwasher_1",
  "action": "delay",
  "value": 20,
  "reason_code": "avoid_new_peak",
  "inside_rules": true,
  "status": "executed",
  "effect": {
    "peak_before_kw": 46.0,
    "peak_after_kw": 40.0,
    "saving_usd": 120.0
  }
}
```

`status`: executed | undone. (The hard case is carried by the Escalation, not by a Decision status.)
There is no per-decision owner approval any more: anything outside the rules becomes an Escalation.
`reason_code`: avoid_new_peak | stay_under_cap | release_into_valley | catch_up | owner_override | escalation_fallback | escalation_choice.
`effect` is computed by the engine. Nobody else changes it. `saving_usd = baseline_cost_usd − optimized_cost_usd` over the
2-hour horizon (demand charges above the month's already-paid peaks + energy), computed marginally in plan order so the
savings of one replan add up.

### Context (Fetch agents → API → engine; numbers forwarded unchanged)

```json
{
  "ts": "...",
  "weather": {
    "label": "live_api",
    "source": "open-meteo",
    "hourly": [{ "ts": "...", "temp_c": 24.1 }]
  },
  "prices": {
    "label": "live_api",
    "source": "caiso",
    "hourly": [{ "ts": "...", "usd_per_kwh": 0.31 }],
    "stress": "high"
  },
  "events": {
    "label": "live_api",
    "source": "ticketmaster",
    "items": [
      {
        "name": "Giants vs Dodgers",
        "venue": "Oracle Park",
        "start": "...",
        "distance_km": 1.8,
        "expected_attendance": 40000
      }
    ]
  },
  "crowd_effect": {
    "value": "medium",
    "set_by": "claude",
    "reason": "Game ends 22:00, 1.8 km away"
  }
}
```

Partial posts merge. `label`: live_api | recorded (demo mode). `stress`: low | normal | high.
`ts` is stamped by the API in sim time when the post arrives. `crowd_effect.set_by`: claude | owner | default.
`events.source` is a free string naming the provider (demo fixtures: `demo_events`, one recorded sports event; the real provider
is Suyog's choice, e.g. Ticketmaster). Grid `prices` are a market signal for forecasts and Claude's context, not the bill (see Tariff).
`crowd_effect.value`: none | small | medium | large → crowd multiplier 1.00 / 1.10 / 1.25 / 1.40 (fixed table in the engine).
Runtime passes the current outdoor temperature and multiplier to the simulation in `sim_tick.inputs` (physical inputs).
Engine uses: crowd effect → forecast of customer-driven (demand_driven) devices; prices → tie-breaks only; weather → kept and
shown, not used by the forecast in this build (no HVAC model). Fetched periodically
(every `CONTEXT_INTERVAL_S`, default 600 real s, and on kitchen build); the engine always uses the latest it has.

### Escalation (engine → runtime → Claude)

```json
{
  "escalation_id": "e_0012",
  "lane": "with",
  "ts": "<sim ts>",
  "updated_ts": "<sim ts>",
  "block_start": "<sim ts>",
  "problem": {
    "forecast_peak_kw": 44.0,
    "target_kw": 40.0,
    "excess_kw": 4.0,
    "reason": "dinner rush + Giants game"
  },
  "options": [
    {
      "option_id": "accept_overrun",
      "summary": "Let the peak reach 43 kW for one block",
      "actions": [],
      "projected": {
        "peak_kw": 43.0,
        "cost_delta_usd": 60.0,
        "max_indoor_temp_change_c": null
      },
      "rule_breaks": [{ "kind": "cap_overrun", "amount": 3.0, "unit": "kW" }],
      "within_authority": true,
      "harm_score": 1.0,
      "rank": 2
    },
    {
      "option_id": "deep_reduce_hvac",
      "summary": "HVAC to 30 % for 15 min",
      "actions": ["<Command>"],
      "projected": {
        "peak_kw": 40.0,
        "cost_delta_usd": 0.0,
        "max_indoor_temp_change_c": null
      },
      "rule_breaks": [
        {
          "kind": "below_min_power",
          "device_id": "hvac_1",
          "amount": 10,
          "unit": "pct"
        }
      ],
      "within_authority": false,
      "harm_score": 0.25,
      "rank": 3
    },
    {
      "option_id": "extend_delay_dishwasher",
      "summary": "Delay the dishwasher 10 min past its deadline",
      "actions": ["<Command>"],
      "projected": {
        "peak_kw": 40.0,
        "cost_delta_usd": 0.0,
        "max_indoor_temp_change_c": null
      },
      "rule_breaks": [
        {
          "kind": "past_deadline",
          "device_id": "dishwasher_1",
          "amount": 10,
          "unit": "min"
        }
      ],
      "within_authority": true,
      "harm_score": 0.5,
      "rank": 1
    }
  ],
  "default_option_id": "extend_delay_dishwasher",
  "active_option_id": "extend_delay_dishwasher",
  "deadline_sim_ts": "<sim ts>",
  "status": "open",
  "resolved_by": null,
  "chosen_option_id": null,
  "rationale": null,
  "claude_attempts": []
}
```

`status`: open | resolved | expired_default | obsolete. `resolved_by`: claude | default (nullable).
Active = `open`; at most one active escalation per lane per `block_start`.
**Opens** on decision ticks when a block starting within 30 sim minutes remains over target after all in-rules moves.
**Fallback:** best-ranked option within authority, else `accept_overrun`. Applied immediately, with
`escalation_fallback` Decisions and Commands in that step; `active_option_id` identifies the fallback. The clock never waits.
**Options:** 1–3 evaluated alternatives: `accept_overrun` always, the best `deep_reduce_<type_id>` and
`extend_delay_<type_id>` when possible. No owner-choice option or owner resolution. Food safety is absolute.
Action templates have `decision_id: null`; execution creates fresh Commands and Decisions.
Each option has non-null projection, harm_score and rank. Every projected peak above target includes `cap_overrun`.
Rank by within_authority first, harm_score, cost_delta_usd, number of affected devices, then option_id.
`harm_score` = sum of rule-break amount / authority tolerance (ENGINE.md §6). Disabled authority permits no Claude choice.
Claude sees **all** ranked alternatives, their authority flags, owner preferences and Fetch.ai context.
**Update:** re-evaluate an open escalation in place on decision ticks. Preserve id, deadline, default and active ids.
If the in-rules plan alone now holds the block, mark `obsolete`; executed commands end at their planned times.
A new risk after closure gets a new id.
**Resolve:** `resolve_escalation(id, option_id, "claude", rationale)` validates current authority, food safety and time.
An accepted choice resolves the escalation and switches devices on the next tick (`escalation_choice`). A rejected
choice leaves the fallback active and records `outside_authority` or `after_deadline`. Claude gets one retry before
the deadline (at most two pre-deadline attempts); unknown option or exhausted retry budget raises RuleError.
`claude_attempts` is a list of `{ts, option_id, accepted, reason, rationale}`; `reason` is null on acceptance,
otherwise `outside_authority` or `after_deadline`. `rationale` is nullable text. Late attempts may be recorded after expiry;
closed resolved/obsolete escalations return unchanged. `chosen_option_id` and `rationale` describe an accepted choice only.
**Deadline:** `max(ts + 5 min, min(ts + 15 min, block_start − 5 min))`. At the deadline an open escalation becomes
`expired_default`, `resolved_by: default`; fallback remains in force.
`rule_breaks[].kind`: cap_overrun | below_min_power | past_deadline | over_max_reduce | over_max_delay.
Projection cost = option cost minus in-rules baseline with the problem block hypothetically held at target,
using tariff energy and per-charge demand peaks; indoor temperature change is null (not modelled).
Runtime publishes `ws escalation` and `live_escalation` with explanation and explanation_source (`ai` | `template`).
Claude explains the choice, acceptance/rejection and reason, quoting only engine numbers; AI off uses template text.
The owner retains `owner_command` and `undo` for manual control.

### Meter

```json
{
  "ts": "...",
  "total_kw": 38.2,
  "block_avg_kw": 37.9,
  "block_start": "...",
  "month_peak_kw": 46.0,
  "on_peak_month_peak_kw": 44.0,
  "peak_mode": "cap",
  "peak_cap_kw": 40.0,
  "target_kw": 40.0,
  "energy_kwh_today": 312.4,
  "energy_kwh_month": 7712.4,
  "price_usd_per_kwh_now": 0.31,
  "cost_usd_today": 61.2,
  "cost_usd_month": 1830.55,
  "demand_peaks": [
    { "name": "max_demand", "peak_kw": 46.0, "usd_per_kw": 20.0, "cost_usd": 920.0 },
    { "name": "peak_demand", "peak_kw": 44.0, "usd_per_kw": 8.0, "cost_usd": 352.0 }
  ]
}
```

Every field is engine-computed from HubReports, warm-up history and the tariff (`price_usd_per_kwh_now`: current energy price the bill uses).
`month_peak_kw`: highest closed 15-min block this billing month (any hour). `on_peak_month_peak_kw`: the month peak of the
**highest-rate windowed charge that applies this month** (B-19: `peak_demand_summer` in June–September, `peak_demand_winter`
otherwise; null if no windowed charge applies). `demand_peaks`: one entry per demand charge **that applies this month**, in tariff
order, with its month peak so far and its cost (`usd_per_kw × peak_kw`); the UI shows these, it never multiplies.
Day and month are local (`tariff.timezone`).
`cost_usd_today` = energy cost today + demand charges added today (peak increases since local midnight × rate).
`cost_usd_month` = energy cost month to date + every applicable demand charge on its peak so far + fixed charges to date.
(`cost_usd_today` also includes today's fixed charges.)
`target_kw`: what the engine is holding now (= `peak_cap_kw` in `cap` mode; engine-chosen in `minimize` mode). `peak_cap_kw` null in `minimize` mode.

### TickState (engine → runtime every step; runtime publishes it to SpacetimeDB)

```json
{
  "lane": "with",
  "ts": "...",
  "hub": "<HubReport>",
  "meter": "<Meter>",
  "customers_per_hour": 64,
  "new_decisions": ["<Decision>"],
  "new_commands": ["<Command>"],
  "new_escalations": ["<Escalation>"],
  "warnings": ["<Warning>"],
  "indoor_temp_c": 22.4,
  "forecast_kw": [38, 41, 44, 39, 36, 35, 37, 40]
}
```

`new_escalations`: every escalation opened **or changed** in this step (full object; upsert by `escalation_id`).
`warnings`: engine warnings raised in this step (`cap_unreachable`), empty otherwise; the runtime forwards them as ws `warning` messages.
`forecast_kw`: next 2 h in 15-min steps (8 values, the first is the block in progress); present only on re-plan ticks, otherwise null.
`hub`: the HubReport this step was computed from (echoed). `customers_per_hour` copied from it; `indoor_temp_c` = the kitchen's one
dining-room temperature (shared by every HVAC unit's `physical.indoor_temp_c`). Both lanes carry `forecast_kw` on decision ticks.
`new_commands`: Commands issued this step (engine and owner); the runtime sends them in the **next** `sim_tick` and forwards the
`with` lane's commands for ESP32-mapped devices to Convex.

### LaneComparison (engine `compare_lanes(without, with_)`, attached by the runtime to every tick pair)

```json
{
  "ts": "...",
  "saved_today_usd": 18.4,
  "peak_avoided_kw": 6.0,
  "month_peak_without_kw": 46.0,
  "month_peak_with_kw": 40.0
}
```

The browser shows these numbers; it never subtracts lanes itself.

### Proposal (AI suggestion waiting for owner confirmation)

```json
{
  "proposal_id": "p_0007",
  "ts": "...",
  "kind": "importance",
  "payload": {
    "device_id": "walk_in_cooler_1",
    "importance": "always_on",
    "limits": {}
  },
  "summary": "Never touch the walk-in after 21:00",
  "status": "pending",
  "created_by": "ai",
  "confirmed_via": null,
  "expires_at": "<sim ts>"
}
```

`kind`: importance | peak*cap | authority | undo_decision | customer_event.
`payload` per kind = the matching `propose*\*`input without`summary`; `authority`payload = ClaudeAuthority.`created_by`: ai.
`status`: pending | confirmed | cancelled | expired. `confirmed_via`: ui | asi_one | null.
Applied by code (never by the model) when the owner confirms; the result is the normal facade call.

### Bill

```json
{
  "period": "2026-07",
  "energy_kwh": 21840.0,
  "energy_cost_usd": 4210.55,
  "demand_charges": [
    { "name": "max_demand", "peak_kw": 46.0, "cost_usd": 920.0 }
  ],
  "fixed_usd": 0.0,
  "total_usd": 5130.55,
  "tariff_id": "demo_tariff_v1"
}
```
`demand_charges`: one entry per tariff demand charge that applies in `period` (seasonal charges outside their months are absent).
`total_usd` = `energy_cost_usd` + Σ `demand_charges[].cost_usd` + `fixed_usd`.

### BacktestResult

```json
{
  "dataset": "<label>",
  "month": "2026-07",
  "policies": { "without": "<Bill>", "timer": "<Bill>", "with": "<Bill>" },
  "checks": {
    "baseline_matches_raw": true,
    "energy_conserved": true,
    "rule_violations": 0
  },
  "assumptions_id": "base",
  "tariff_id": "pge_b19_secondary_voluntary",
  "partial": false,
  "saved_usd": 412.35,
  "saved_vs_timer_usd": 160.1
}
```
The month mark of the Proof chart. `saved_usd` = `policies.without.total_usd − policies.with.total_usd` and `saved_vs_timer_usd` =
`policies.timer.total_usd − policies.with.total_usd`, computed by the engine (the browser never subtracts). `partial`: true for a
month with fewer scored days than calendar days (the first month after the 4 warm-up weeks). `month` is in the replay calendar
(dataset dates + `day_offset`).

### BacktestPoint (one per replayed local day; the Proof chart's running line)
```json
{
  "dataset": "<label>",
  "assumptions_id": "base",
  "tariff_id": "pge_b19_secondary_voluntary",
  "month": "2026-07",
  "day": "2026-07-14",
  "ts": "2026-07-15T07:00:00Z",
  "partial": false,
  "cost_to_date_usd": { "without": 2210.4, "timer": 2105.9, "with": 2001.2 },
  "saved_month_to_date_usd": 209.2,
  "saved_vs_timer_month_to_date_usd": 104.7,
  "saved_year_to_date_usd": 1530.8
}
```
`ts` = end of the local day (UTC). `cost_to_date_usd[policy]` = that policy's month-to-date bill on the tariff (energy so far + each
applicable demand charge on its month peak so far + fixed charges so far: the Meter `cost_usd_month` definition), so the saved line
can jump when a policy sets a new demand peak. The last point of a month equals that month's BacktestResult to the cent
(`saved_month_to_date_usd == saved_usd`). `saved_year_to_date_usd` = Σ `saved_usd` of earlier months + `saved_month_to_date_usd`.

### BacktestInputs (built by the caller, passed to `run_backtest`; the engine reads no files)
```json
{
  "config": "<KitchenConfig>",
  "tariff": "<Tariff>",
  "catalog": ["<EquipmentType>"],
  "seed": 42,
  "series": "<WarmUpHistory: per-device 15-min blocks covering the 4 warm-up weeks + every replayed month>",
  "assumptions": { "assumptions_id": "base", "flex_scale": 1.0, "draw_scale": 1.0, "forecast_noise_pct": 0.0 }
}
```
`series` uses the WarmUpHistory shape (`source: "nrel_comstock"`, `label: "calibrated_model"`): built by `backend/data/`
(`load_backtest_inputs(months, assumptions_id)`) from the ComStock year with the distribution recipe (DATA_AND_PROOF.md) and
`assumptions.yaml`; the per-device blocks sum exactly to the dataset's electricity total of every row, and no block exceeds its
device's `rated_kw` (the loader raises otherwise; it never clips). `assumptions` are the sensitivity knobs the engine applies
itself (seeded, labelled): `flex_scale` scales owner limits' flexibility, `draw_scale` scales device draw, `forecast_noise_pct` adds
seeded forecast noise. `base` = 1.0 / 1.0 / 0.0.

---

## 2. Seam 1 — REST + WebSocket (Frontend ↔ API)

### REST

| Method | Path                                          | Body → Returns                                                                                                                                                                |
| ------ | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/catalog`                                | → list[EquipmentType]                                                                                                                                                         |
| POST   | `/api/kitchen`                                | KitchenConfig → `{ kitchen_id }` (builds both engine lanes with `Kitchen.build_lanes`, warms them up from `data.warmup.build_warmup(...)`, sends `sim_build` to the sim host) |
| GET    | `/api/kitchen`                                | → `{ config: KitchenConfig, devices: list[Device], tariff: Tariff }`                                                                                                          |
| PUT    | `/api/kitchen/devices/{device_id}/importance` | `{ importance, limits }` → Device                                                                                                                                             |
| PUT    | `/api/kitchen/peak-cap`                       | `{ peak_mode, peak_cap_kw }` → Meter (`peak_cap_kw` required for `cap`, null for `minimize`)                                                                                  |
| POST   | `/api/sim/control`                            | `{ action: "play" \| "pause" \| "reset" \| "next_day", speed?: 120 }` → ClockState (`next_day` only while `paused_reason` is `run_complete`; else 422)                        |
| POST   | `/api/devices/{device_id}/command`            | `{ action, value? }` → Command (manual click, `issued_by: owner`)                                                                                                             |
| POST   | `/api/events/customers`                       | `{ customers: 40, duration_min: 60 }` → ok (queued as a surge in the next `sim_tick`)                                                                                         |
| POST   | `/api/decisions/{decision_id}/undo`           | → Decision (status `undone`)                                                                                                                                                  |
| GET    | `/api/decisions?limit=50`                     | → list[Decision]                                                                                                                                                              |
| POST   | `/api/backtest/run`                           | `{ months: ["2026-07"], assumptions_id }` → `{ run_id: "run_0001" }`                                                                                                          |
| GET    | `/api/backtest/{run_id}`                      | → list[BacktestResult]                                                                                                                                                        |
| POST   | `/api/chat`                                   | `{ message }` → `{ chat_id: "chat_0001" }` (reply streams over WebSocket)                                                                                                     |
| GET    | `/api/proposals?status=pending`               | → list[Proposal]                                                                                                                                                              |
| POST   | `/api/proposals/{proposal_id}/confirm`        | `{ confirm: true \| false }` → Proposal (owner confirmation from the UI)                                                                                                      |
| PUT    | `/api/kitchen/authority`                      | ClaudeAuthority → ok (owner only)                                                                                                                                             |
| PUT    | `/api/kitchen/preferences`                    | `{ text }` → ok                                                                                                                                                               |
| GET    | `/api/context`                                | → Context                                                                                                                                                                     |
| POST   | `/api/context`                                | partial Context → ok (agents, header `X-Agent-Token`)                                                                                                                         |
| POST   | `/api/context/crowd-effect`                   | `{ value, reason }` → ok (Concierge, `X-Agent-Token`)                                                                                                                         |
| GET    | `/api/escalations?status=open`                | → list[Escalation]                                                                                                                                                            |
| POST   | `/api/agent-log`                              | AgentLog → ok (agents, `X-Agent-Token`)                                                                                                                                       |
| GET    | `/api/health`                                 | → `{ ok, kitchen_impl, live_transport, store, hardware, sim_host }` (Azure health probe)                                                                                      |

Conventions: "→ ok" = `{ "ok": true }`. Errors: `{ "detail": "text" }` with 422 (RuleError, invalid body) or 404 (unknown id).
Health values: `kitchen_impl` fake | real · `live_transport` spacetime | ws · `store` convex | memory · `hardware` off | sim_bridge | esp32 ·
`sim_host` connected | offline.
ClockState = `{ playing, speed, sim_ts, tick_id, paused_reason, day_index, run_days, phase }` (the ws `clock` message without `type`).
`day_index`: 1-based service day of this run · `run_days`: days planned (grows by 1 on each `next_day`) ·
`phase`: `service` (open, ticks at `speed`) | `overnight` (closed hours, ticks at max speed, `sim_tick.fast_forward: true`) |
`closed` (after the last day's close, waiting for `next_day`).

### WebSocket `/ws` (server → client)

```json
{ "type": "tick", "data": "<TickState>" }
{ "type": "decision", "data": "<Decision>", "explanation": "text", "explanation_source": "ai | template" }
{ "type": "clock", "playing": true, "speed": 120, "sim_ts": "...", "tick_id": 1095, "paused_reason": null, "day_index": 1, "run_days": 1, "phase": "service" }
{ "type": "warning", "code": "cap_unreachable", "message": "text", "data": { "unavoidable_kw": 44.0, "peak_cap_kw": 40.0, "target_kw": 40.0 } }
{ "type": "chat_delta", "chat_id": "...", "text": "partial text" }
{ "type": "chat_done", "chat_id": "..." }
{ "type": "backtest_progress", "run_id": "...", "month": "2026-07", "pct": 40 }
{ "type": "backtest_point", "run_id": "...", "data": "<BacktestPoint>" }
{ "type": "backtest_month", "run_id": "...", "data": "<BacktestResult>" }
{ "type": "comparison", "data": "<LaneComparison>" }
{ "type": "proposal", "data": "<Proposal>" }
{ "type": "escalation", "data": "<Escalation>", "explanation": "text", "explanation_source": "ai | template" }
{ "type": "context", "data": "<Context>" }
{ "type": "agent_log", "data": "<AgentLog>" }
```

`/ws` is the **viewer** socket (chat streaming, proposals, and everything when `LIVE_TRANSPORT=ws`). The sim host's hub uses a
separate socket, `/ws/hub` (section 8).
`paused_reason`: null | manual (owner or presenter pressed pause) | hub_waiting (no `hub_report` within 2 real s) | sim_host_offline
(no hub connected) | run_complete (the last planned day has closed; `phase: closed`). The clock never slows or pauses for an escalation or a proposal: the engine applies its fallback at once and
Claude answers asynchronously (ENGINE.md section 6). Manual pause/resume is a runtime control, invisible to the engine and the backtest.
Ticks are sent for both lanes. The UI throttles rendering to ~4 per second.
`warning.data` per code: cap_unreachable `{ unavoidable_kw, peak_cap_kw, target_kw }` (`peak_cap_kw` null in minimize mode) · sim_host_offline `{ last_tick_id }` ·
hub_offline `{ device_id, hub_id }` · live_transport_down `{}` · store_down `{}`.
`warning.code`: cap_unreachable | sim_host_offline (no `/sim` tab connected; clock paused) |
hub_offline (no ESP32 reading for 30 s; that device falls back to simulated) |
live_transport_down (SpacetimeDB unreachable; switched to /ws) | store_down (Convex unreachable; switched to memory).

**Live transport.** With `LIVE_TRANSPORT=spacetime` (default) the runtime publishes ticks, comparison, feed and clock
to SpacetimeDB (section 5) and every UI tab subscribes there (the UI's only live source); chat, configuration proposals and manual commands still use REST + `/ws`.
With `LIVE_TRANSPORT=ws` every message above goes over `/ws` (offline fallback).

---

## 3. Seam 2 — Engine facade (API ↔ Engine, Python)

`from engine import Kitchen, run_backtest, compare_lanes, RuleError` — nothing else from the engine is public.
The engine does no I/O: HubReports and context come in and Commands go out as plain objects. The signatures below are what
the runtime and FakeKitchen build against; how the engine works behind them is in `docs/design/ENGINE.md`.
Call order is part of the contract: every tick the runtime steps `without`, then `with`, and calls id-creating methods
(`owner_command`) in that lane order, so the shared id counters are deterministic. Undo and escalation resolution use the `with` lane.

| Call                                                                   | Returns                                                                                                                                                                                          | Notes                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Kitchen.build_lanes(config, tariff, catalog, seed)` | `{"without": Kitchen, "with": Kitchen}`                                                                                                                                                          | `catalog`: list[EquipmentType], the same list `GET /api/catalog` serves and `sim_build.catalog` carries (`backend/data/equipment_catalog.json`, loaded by the runtime; the engine reads no files). Both lanes sharing one id allocator (`d_`, `c_`, `e_` counters, monotonically increasing, never reset during a run). |
| `Kitchen(config, tariff, catalog, control, seed, ids=None)` | Kitchen                                                                                                                                                                                          | `catalog`: list[EquipmentType]; every `config.equipment[].type_id` must be in it (else `RuleError`). `tariff`: Tariff (section 1). `control`: `"without"` or `"with"`. Single lane (tests). |
| `warm_up(history)`                                                     | None                                                                                                                                                                                             | `history`: WarmUpHistory (section 1). Call once per lane before the first `step`. Raises `ValueError` if a block ends after `history.end`. Not called → the engine runs on live history only.                                                                                                                                                                   |
| `step(minutes, hub_report)`                                            | TickState                                                                                                                                                                                        | Meters this lane's HubReport for the minute just simulated; replans every 5 sim min; returns `new_commands` to deliver next tick.                                                                                                                                                                                                                               |
| `ingest_reading(reading)`                                              | Device                                                                                                                                                                                           | Overrides that device's power in the next `step` with a measured Reading; `source` becomes measured. `with` lane only.                                                                                                                                                                                                                                          |
| `owner_command(device_id, action, value)`                              | Command                                                                                                                                                                                          | Manual click on any device. Records an `owner_override` Decision; the engine won't override the device for 30 sim min. Returned in the next step's `new_commands`, delivered in the following `sim_tick`. The runtime calls it on both lanes (`without` first) so the comparison stays fair.                                                                    |
| `set_importance(device_id, importance, limits)`                        | Device                                                                                                                                                                                           | Raises `RuleError` for unsafe limits.                                                                                                                                                                                                                                                                                                                           |
| `set_peak_cap(peak_mode, peak_cap_kw)`                                 | Meter                                                                                                                                                                                            | `with` lane decisions only; raises `RuleError` for `cap` without a number                                                                                                                                                                                                                                                                                       |
| `undo(decision_id)`                                                    | Decision                                                                                                                                                                                         | `with` lane. Only `executed` reduce / delay decisions (else RuleError): reduce → `restore`; delay → `start` (job waiting) or `delay 0` (idle hold). Status `undone`; device protected 30 sim min.                                                                                                                                                               |
| `set_context(context)`                                                 | None                                                                                                                                                                                             | Merges context; used from the next step. Plain object, no I/O.                                                                                                                                                                                                                                                                                                  |
| `set_authority(authority)` · `set_preferences(text)`                   | None                                                                                                                                                                                             | `with` lane only                                                                                                                                                                                                                                                                                                                                                |
| `open_escalations()`                                                   | list[Escalation]                                                                                                                                                                                 |                                                                                                                                                                                                                                                                                                                                                                 |
| `resolve_escalation(escalation_id, option_id, resolved_by, rationale)` | Escalation | Claude only; validates authority and deadline, records attempt verdict, one retry. Accepted choice switches next tick; rejected choice keeps fallback. Unknown option → RuleError. |
| `forecast(horizon_min)`                                                | list[float]                                                                                                                                                                                      | kW per 15 min, 8 values. `horizon_min` is fixed at 120 in this build (other values → ValueError). Latest decision tick's forecast.                                                                                                                                                                                                                              |
| `what_if(device_id, action, value, at)`                                | Effect `{peak_before_kw, peak_after_kw, saving_usd}`                                                                                                                                             | `at`: sim ts where the hypothetical command starts, within `[now, now + 120 min)` (else RuleError). Read-only: no state, commands, ids or escalations change. Per lane; the runtime picks the lane (default `with`).                                                                                                                                            |
| `snapshot()`                                                           | `{ tick_id, sim_ts, lane, control, peak_mode, config, meter, forecast_kw, forecast_ts, devices, active_commands, owed_kwh, open_escalations, warnings, recent_decisions, context, id_counters }` | Per lane; pure (no side effects, no I/O). `recent_decisions`: last 20, newest first. `devices`: latest HubReport state. `active_commands`: Commands acked and still in force. The runtime and AI use the `with` lane                                                                                                                                            |
| `run_backtest(inputs, months, assumptions_id, on_progress=None)` | list[BacktestResult] | Module-level, pure (no I/O). `inputs`: BacktestInputs built by the caller with `backend/data` (`load_backtest_inputs`); the engine never opens a file. Replays every month in `months` under `without` / `timer` / `with` at full speed (15-min steps, decider every step, escalations end on the fallback, no Claude). `on_progress(event)` is called synchronously with plain objects in order: `{"type": "backtest_point", "data": BacktestPoint}` once per local day, `{"type": "backtest_month", "data": BacktestResult}` at each month end, `{"type": "backtest_progress", "month", "pct"}`. The caller paces publishing (the engine never sleeps). Same inputs → identical events. |
| `compare_lanes(without, with_)`                                        | LaneComparison                                                                                                                                                                                   | Module-level function over two TickStates.                                                                                                                                                                                                                                                                                                                      |
| `RuleError`                                                            | exception                                                                                                                                                                                        | Raised for unsafe limits or moves. API maps it to HTTP 422.                                                                                                                                                                                                                                                                                                     |

`FakeKitchen` (in `backend/fakes/`) implements every call above with canned results from `contracts/fixtures/facade/`.
Customer arrivals are simulated in the browser (section 9); surges reach them through `sim_tick.surges`.

---

## 4. AI tools (Claude tool use, implemented by the API on top of the facade)

| Tool                        | Calls                                                        | Notes                                                                                                                                                 |
| --------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_kitchen_state`         | `snapshot()`                                                 |                                                                                                                                                       |
| `get_forecast`              | `forecast(120)`                                              | Input `{}`                                                                                                                                            |
| `explain_decision`          | decision from `snapshot()`                                   | Input `{ decision_id }`. Returns facts; the AI writes the sentence                                                                                    |
| `what_if`                   | `what_if(...)`                                               | Input `{ device_id, action, value, at, lane? }` (`lane` default `with`; `at` = sim ts the hypothetical starts). For "what if I delay the dishwasher?" |
| `get_bill`                  | `snapshot()` meter, or a stored engine Bill / BacktestResult | Input `{ period: "YYYY-MM" }`. Never computed by the agent or the store                                                                               |
| `propose_importance_change` | —                                                            | Input `{ device_id, importance, limits, summary }` → Proposal (`kind: importance`)                                                                    |
| `propose_peak_cap_change`   | —                                                            | Input `{ peak_mode, peak_cap_kw, summary }` → Proposal (`kind: peak_cap`)                                                                             |
| `propose_undo`              | —                                                            | Input `{ decision_id, summary }` → Proposal (`kind: undo_decision`)                                                                                   |
| `propose_customer_event`    | —                                                            | Input `{ customers, duration_min, start_sim_ts, summary }` → Proposal (`kind: customer_event`), applied as a surge                                    |

| `get_context` | `snapshot()` context | |
| `get_escalation` | `open_escalations()` | Options with engine numbers |
| `choose_escalation_option` | → runtime → `resolve_escalation(..., "claude", rationale)` | Input is an `option_id` from the offered list (enum-constrained). Code validates authority |
| `set_crowd_effect` | → `POST /api/context/crowd-effect` | Input is a category (enum), never a number |

Rules:

- The AI may only quote numbers that came back from a tool.
- Two bounded tools change state: `choose_escalation_option` (an offered id, validated by code against the owner's authority)
  and `set_crowd_effect` (a category). Everything else is a Proposal.
- Apart from those two, the model has no tool that changes state. Every other change is a Proposal applied by code after an owner confirmation:
  UI Confirm (`POST /api/proposals/{id}/confirm`), an ASI:One card button, or a `confirm` / `yes` reply to the latest
  pending Proposal, detected by code in `agents/concierge.py`, not by the model.
- The same agent and tools serve the dashboard chat and the Fetch.ai uAgent (Agent Chat Protocol, ASI:One).

---

## 5. SpacetimeDB tables (live shared kitchen; module in `spacetime/`)

Current state only, small rows, one batched write per real tick. Fields mirror section 1.

| Table             | Key                            | Fields                                                                                                                                                                                                                                                                                                                                                                                               | Written by |
| ----------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `live_tick`       | `lane`                         | ts, tick_id, total_kw, block_avg_kw, month_peak_kw, on_peak_month_peak_kw, peak_mode, peak_cap_kw, target_kw, energy_kwh_today, energy_kwh_month, price_usd_per_kwh_now, cost_usd_today, cost_usd_month, demand_peaks_json, customers_per_hour, indoor_temp_c, forecast_kw_json, forecast_ts. Also the month-to-date store: on a rebuild in the same month the runtime reads it back into `WarmUpHistory.month_to_date` | runtime    |
| `tick_history`    | `lane` + `ts`                  | ts, total_kw, block_avg_kw (last 180 sim minutes per lane; older rows deleted)                                                                                                                                                                                                                                                                                                                       | runtime    |
| `live_device`     | `key` = `"<lane>:<device_id>"` | key, lane, device_id, type_id, name, importance, state, power_kw, rated_kw, power_pct, source, physical_json (what the kitchen floor draws, for every tab)                                                                                                                                                                                                                                           | runtime    |
| `live_comparison` | single row (`id` = 0)          | LaneComparison fields                                                                                                                                                                                                                                                                                                                                                                                | runtime    |
| `live_feed`       | `decision_id`                  | lane, ts, device_id, action, value, status, reason_code, effect_json, explanation, explanation_source (last 50)                                                                                                                                                                                                                                                                                      | runtime    |
| `live_clock`      | single row (`id` = 0)          | playing, speed, sim_ts, tick_id, paused_reason, day_index, run_days, phase, sim_host (connected \| offline)                                                                                                                                                                                                                                                                                          | runtime    |
| `live_context`    | single row (`id` = 0)          | weather_summary, weather_label, prices_summary, prices_label, events_summary, events_label, crowd_effect                                                                                                                                                                                                                                                                                             | runtime    |
| `live_escalation` | `escalation_id`                | lane, status, block_start, updated_ts, problem_json, options_json (with `harm_score`, `rank`), default_option_id, active_option_id, deadline_sim_ts, chosen_option_id, resolved_by, rationale, claude_attempts_json, explanation, explanation_source (last 20; upserted on every change)                                                                                                                                                                    | runtime    |
| `live_agent_log`  | auto id                        | ts_real, from_agent, to_agent, kind, summary (last 300)                                                                                                                                                                                                                                                                                                                                              | runtime    |
| `backtest_point`  | `key` = `"<run_id>:<day>"`     | run_id, day, month, ts, partial, cost_to_date_json, saved_month_to_date_usd, saved_vs_timer_month_to_date_usd, saved_year_to_date_usd, dataset, tariff_id, assumptions_id (latest run only; ≤ 366 rows) | runtime |
| `backtest_month`  | `key` = `"<run_id>:<month>"`   | run_id, month, partial, saved_usd, saved_vs_timer_usd, policies_json, checks_json, dataset, tariff_id, assumptions_id (latest run only; ≤ 12 rows) | runtime |
| `surge_request`   | auto id                        | customers, duration_min, requested_by (identity), created_at, consumed                                                                                                                                                                                                                                                                                                                               | any viewer |

| Reducer                                                                                           | Who may call          | Does                                                                                                                                                                                          |
| ------------------------------------------------------------------------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `publish_ticks(payload_json)`                                                                     | runtime identity only | Upserts live_tick, tick_history, live_device, live_comparison for both lanes. Payload: `{ live_tick: [2], tick_history: [2], live_device: [every device, both lanes], live_comparison: {…} }` |
| `publish_feed(decision_json)`                                                                     | runtime identity only | Upserts a live*feed row (template text first, AI text later). Other `publish*\*`/`log_agent` reducers also take the row as a JSON string                                                      |
| `set_clock(playing, speed, sim_ts, tick_id, paused_reason, day_index, run_days, phase, sim_host)` | runtime identity only | Updates live_clock                                                                                                                                                                            |
| `publish_context(json)` · `publish_escalation(json)` · `log_agent(json)`                          | runtime identity only | Upserts / appends                                                                                                                                                                             |
| `publish_backtest_point(json)` · `publish_backtest_month(json)` · `reset_backtest(run_id)` | runtime identity only | Upsert a Proof row · clear the previous run's rows when a new run starts |
| `reset_all()`                                                                                     | runtime identity only | Clears live tables (new kitchen)                                                                                                                                                              |
| `request_surge(customers, duration_min)`                                                          | anyone                | Inserts surge_request (customers 1 to 80, duration 15 to 120 min)                                                                                                                             |
| `consume_surge(id)`                                                                               | runtime identity only | Marks a surge consumed                                                                                                                                                                        |

Calls go through `backend/live/spacetime_client.py` (Kritazya), which the runtime uses. It calls reducers over HTTP (`POST /v1/database/<db>/call/<reducer>`, JSON array of args) and reads new
surge requests with the SQL endpoint each tick. The engine never sees SpacetimeDB.

---

## 6. Convex tables (durable records + ESP32 bridge; code in `convex/`)

| Table               | Fields                                                                                              | Written by                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `kitchens`          | config (KitchenConfig), created_at                                                                  | API on `POST /api/kitchen`                                  |
| `decisions`         | Decision fields + lane, explanation, explanation_source                                             | runtime (batched once per real second)                      |
| `commands`          | Command fields + lane, hub_id (null if simulated only), delivery: queued \| sent \| acked \| failed | runtime; ESP32 acks                                         |
| `readings`          | Reading                                                                                             | ESP32 via `devices:report`                                  |
| `device_map`        | hub_id, channel, device_id, scale                                                                   | set up once per demo kitchen                                |
| `hubs`              | hub_id, last_seen, firmware                                                                         | ESP32 heartbeat                                             |
| `proposals`         | Proposal                                                                                            | API / agent                                                 |
| `bills`             | Bill + lane                                                                                         | runtime at month end and on demand                          |
| `backtest_results`  | BacktestResult + run_id                                                                             | API after `run_backtest`                                    |
| `device_blocks`     | lane, device_id, block_start, avg_kw, source                                                        | runtime, every closed 15-min block (simulated and measured) |
| `escalations`       | Escalation (final state)                                                                            | runtime                                                     |
| `context_snapshots` | Context + ts                                                                                        | runtime, hourly                                             |

| Function                                                                                                                                                                                                                                       | Type                     | Caller                                                                         |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | ------------------------------------------------------------------------------ |
| `commands:forDevice(hub_id)`                                                                                                                                                                                                                   | query (ESP32 subscribes) | ESP32                                                                          |
| `commands:ack(command_id, ok, applied_value, reason)`                                                                                                                                                                                          | mutation                 | ESP32 (same meaning as CommandAck)                                             |
| `devices:report(reading)`                                                                                                                                                                                                                      | mutation                 | ESP32, and the runtime on behalf of the browser hub when `HARDWARE=sim_bridge` |
| `hubs:heartbeat(hub_id)`                                                                                                                                                                                                                       | mutation                 | ESP32                                                                          |
| `commands:enqueue({ command, lane, hub_id })` · `decisions:record({ decisions: [Decision + lane, explanation, explanation_source] })` · `proposals:upsert({ proposal })` · `bills:save({ bill, lane })` · `backtest:save({ run_id, results })` | mutation                 | runtime / API                                                                  |

ESP32 fail safe: no Convex contact for 30 s → every load returns to normal operation. Runtime: no reading for a mapped
device for 30 s → that device falls back to simulated and a `hub_offline` warning is emitted.

---

## 7. S5 — Agent messages (Fetch uAgents)

| Model                                | Direction                       | Fields                                                                                       |
| ------------------------------------ | ------------------------------- | -------------------------------------------------------------------------------------------- |
| `WeatherRequest` / `WeatherResponse` | concierge → weather → concierge | `lat, lon, hours` / `hourly[{ts, temp_c}], source, label`                                    |
| `PriceRequest` / `PriceResponse`     | concierge → grid → concierge    | `region` (e.g. `"caiso_np15"`)`, hours` / `hourly[{ts, usd_per_kwh}], stress, source, label` |
| `EventsRequest` / `EventsResponse`   | concierge → events → concierge  | `lat, lon, radius_km, window_h` / `items[...]` (Context.events), `source, label`             |
| Agent Chat Protocol                  | owner (ASI:One) ↔ concierge     | Fetch standard; acknowledgements on every message                                            |

### AgentLog (every agent message, for the Agent Network view)

```json
{
  "ts_real": "...",
  "from_agent": "concierge",
  "to_agent": "weather",
  "kind": "request",
  "summary": "Forecast 6 h for 37.80,-122.44"
}
```

`kind`: request | response | post | error. Agent names: concierge | weather | grid | events | claude | engine.
Responses are reshaped into Context and posted unchanged to `POST /api/context`.

---

## 8. S6 — Hub protocol (browser hub ↔ FastAPI, WebSocket `/ws/hub`)

The hub in the sim host tab (`frontend/src/hub/`) is the only client of `/ws/hub`. One JSON message per frame,
`{ "type": ..., ... }`. FastAPI owns time: the hub never steps on its own.

**Hub → server**

```json
{ "type": "hub_hello", "protocol": 1, "hub_id": "sim_hub", "role": "sim_host", "client": "wattwise-web/0.1" }
{ "type": "hub_report", "tick_id": 1095, "reports": { "without": "<HubReport>", "with": "<HubReport>" } }
```

**Server → hub**

```json
{ "type": "hub_welcome", "accepted": true, "reason": null, "tick_id": 0 }
{ "type": "sim_build", "kitchen_id": "k_01", "config": "<KitchenConfig>", "catalog": ["<EquipmentType>"],
  "devices": ["<Device>"], "seed": 42, "start_sim_ts": "2026-07-18T00:30:00Z" }
{ "type": "sim_tick", "tick_id": 1095, "sim_ts": "2026-07-17T19:14:00Z", "minutes": 1,
  "surges": [ { "surge_id": "s_0003", "customers": 40, "duration_min": 60 } ],
  "inputs": { "outdoor_temp_c": 27.5, "crowd_multiplier": 1.25, "is_open": true },
  "commands": ["<Command>"], "replay": false, "fast_forward": false }
{ "type": "sim_control", "action": "play | pause | reset", "speed": 120, "paused_reason": null }
```

Rules:

- `sim_build.devices` is the roster only (`state: "off"`, 0 kW, no `physical`); the simulation sets real state on tick 1.
  `start_sim_ts` example = Friday 17 July 2026, 17:30 local.
- A surge appears once, in the `sim_tick` where it starts; the simulation keeps it active for `duration_min`.
- `hub_welcome.accepted: false` with `reason: "host_taken"` when another sim host is connected; that tab stays a viewer.
- Order inside one tick: the hub applies `commands` (each to its `lane`) → the simulation steps both lanes `minutes` minutes
  from `sim_ts` with the same customer stream + `surges` → the hub replies `hub_report` with the same `tick_id`; each HubReport's
  `ts` = `sim_ts + minutes`.
- The server sends tick _n + 1_ only after `hub_report` _n_ arrives (or the hub reconnects). No report within 2 real s →
  clock `paused_reason: hub_waiting`; socket closed → `sim_host_offline`. On reconnect the server re-sends `sim_build`, then
  replays every past `sim_tick` with `"replay": true` at full speed (same commands, same surges); the hub answers only the last
  replayed tick, and the engine is not re-stepped. The deterministic simulation lands in the same state. The hub knows which
  replayed tick is last from `hub_welcome.tick_id` (the last tick the server completed): it answers the replayed tick with that id.
- Speed only changes the server's send interval (`0.5 s × 120 / speed`); one tick is always 1 sim minute.
- Cadence: the hub reports every tick (needed for exact energy, 15-min peak blocks and smooth live charts); the engine meters
  every report and makes decisions on every 5th tick (`tick_id % 5 == 0`). Commands can therefore appear only in the tick after a
  decision tick, or after an owner action / escalation choice.
- `inputs` are physical facts from context (outdoor temperature, crowd multiplier, opening hours), never engine decisions.
  Missing context → the simulation's built-in summer-day curve and multiplier 1.0.
- The hub never sends numbers the simulation did not produce, and never receives forecasts or decisions, only Commands.

**Day lifecycle (runtime-owned; the engine and the simulation only see ticks).**
| Phase | Sim time | Ticks | `inputs.is_open` | `fast_forward` |
|---|---|---|---|---|
| `service` | day 1: `start_sim_ts` → close · later days: open → close | at `speed` | true | false |
| `overnight` | close → next open (720 ticks for 22:00–10:00) | back to back, as fast as hub reports arrive | false | true |
| `closed` | after the last planned day's close | none (`paused_reason: run_complete`) | – | – |

- Every overnight tick is a normal tick: the hub reports it, the engine meters it and decides on every 5th tick, so always-on and
  cycling loads (refrigeration, freezer, ice machine, standby water heater, HVAC setback) are billed exactly. Nothing is skipped.
- `fast_forward: true` tells the hub not to re-render per tick; the physics is identical.
- Day _d_ < `run_days` ends at close → the runtime runs that night → day _d + 1_ starts at open. After the last day's close the
  clock stops (`phase: closed`); `next_day` runs the night, then one more service day.
- Overnight publishing: the runtime publishes `publish_ticks` once per closed 15-min block (not per tick) and `set_clock` once per
  block, so viewers see the night as block rows; the engine still receives every tick.

---

## 9. S7 — Appliance interface (simulation ↔ hub, TypeScript, inside the browser)

| Call                              | Returns    | Caller     | Notes                                                                       |
| --------------------------------- | ---------- | ---------- | --------------------------------------------------------------------------- |
| `appliance.step(minutes, inputs)` | void       | simulation | Physics + customer-driven usage; seeded randomness only                     |
| `appliance.reading()`             | Device     | hub only   | 0 ≤ `power_kw` ≤ `rated_kw`                                                 |
| `appliance.apply(command)`        | CommandAck | hub only   | Executes on / off / start / delay / reduce / restore within physical limits |

Only the simulation and the hub depend on this seam (both Ashirwad), so it may change on the `ashirwad` branch without a
contract sync; whatever reaches HubReport or CommandAck still follows section 1. Power models and the equipment catalog:
`docs/design/SIMULATION.md`. A real ESP32 is a second hub: Commands in through Convex, Readings out (section 6).
