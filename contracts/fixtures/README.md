# contracts/fixtures — shared fake data

**FAKE DATA — not measured, not live.** Every number comes from a toy simulation plus a scripted "engine" in
`generate.py`. Engine internals are TBD (docs/design/ENGINE.md), so these are illustrative values, not engine output.
Backtest and bill numbers here are invented and must never be shown as savings (`backtest-auditor` rule).

Owner: Kritazya. Changes go by PR. Built by the `fixture-builder` subagent from `docs/CONTRACTS.md` (prose; there are no
`backend/contracts/` models yet). Every former gap now has a demo decision in CONTRACTS.md (`/Main_Gaps.md`); see `GAPS.md`.

## Regenerate and check
```
python3 contracts/fixtures/generate.py      # seed 42, stdlib only, identical bytes on every run
python3 contracts/fixtures/check.py         # shapes, enums, invariants, cross-refs, determinism; non-zero on failure
```
Never hand-edit a JSON file: change `generate.py`, regenerate, run `check.py`.

## The scenario (Demo Café, `scenario/demo_cafe/`)
Friday 17 July 2026, 17:30 to 19:30 America/Los_Angeles (UTC in data, start `2026-07-18T00:30:00Z`), 120 ticks of 1 sim
minute, both lanes, `peak_mode: "cap"` at 40 kW (Meter `target_kw` = 40). Tariff `demo_tariff_v1` (`shapes/tariff.json`,
label `illustrative`): the whole window is in the 16:00–21:00 peak period, so every Meter price is $0.38/kWh and both demand
charges ($20/kW max + $8/kW peak-period) apply. Context grid prices are only a market signal and never bill anything.
Recorded context (hot evening, high grid prices, Giants game from `demo_events`, crowd `medium`) is posted before tick 1
and refreshed at tick 61. A judge surge (+40 customers, 60 min) is requested at tick 30 and delivered once in `sim_tick` 31
(`s_0001`). Routine `with`-lane decisions happen only on ticks where `tick_id % 5 == 0`. Escalation `e_0001` opens at tick 60
(deadline = ts + 15 min, capped at block_start − 5 min). The scenario runs outside demo mode, so the clock slows to 1×
(`slowed_reason: "escalation"`) instead of pausing. Claude chooses `extend_delay_dishwasher` (rule breaks `past_deadline` 20 min +
`over_max_delay` 15 min, both within authority); its new Command is issued at tick 61 and delivered at 62. The `without` lane
reaches a 49.2 kW block; every closed `with` block stays at or under 40 kW. All HVAC units share one dining-room temperature.
`scenario.json` has the timeline, the tariff and the fake starting stats; `index.json` lists the streams and every id.

## Files
| Folder | What | Consumed by |
|---|---|---|
| `shapes/` | One example per §1 shape. Variants: kitchen_config cap + `kitchen_config_minimize`; `tariff`; hub_report/tick_state with + without; command (engine) + `command_owner`; command_ack ok / clamped (`ok: true`, `out_of_range`) / rejected (`ok: false`, `job_running`); escalation open / resolved_by claude / awaiting_owner / expired_default; one Proposal per kind (`proposal_pending` / `proposal_confirmed` = importance, plus `proposal_<kind>`); device + device_measured. Escalation variants other than "resolved" are alternative outcomes of `e_0001`, not part of the stream. | everyone (generated types, tests) |
| `hub_protocol/` | §8 messages, one file per type (+ `sim_tick_replay.json` with `replay: true`), plus `server_to_hub.jsonl` (hub_welcome, sim_build, 120 sim_ticks with `replay: false`) and `hub_to_server.jsonl` (hub_hello, 120 hub_reports; each lane's HubReport carries its own `acks`) | Ashirwad: `src/mocks/mockHubServer.ts` plays `server_to_hub.jsonl`; the sim's determinism test compares against `hub_to_server.jsonl` · Suyog: `fakes/fake_hub_client.py` answers each `sim_tick` with the matching line of `hub_to_server.jsonl` · Kritazya: HubReports as engine input |
| `rest/` | One file per §2 endpoint: `{method, path, status, request, response}` (+ `_422` / `_404` error examples, `{detail}` bodies) | Ashirwad: `src/mocks` REST handlers (match method + path) · Suyog: API tests |
| `ws/` | One file per `/ws` message type + `stream.jsonl` (clock, context, agent_log, then per tick: tick without, tick with, comparison, decisions, escalations; slowed / restored clock around the escalation) | Ashirwad: `/ws` fallback mock · Suyog: API tests |
| `facade/` | §3 calls as `{call, args, returns}` (`raises` on `set_importance_rule_error`, `set_peak_cap_rule_error`) + `step_stream.jsonl`: per tick and lane `{args: {minutes, hub_report}, returns: TickState}` | Suyog: `fakes/fake_kitchen.py` (look up `step` by `hub_report.lane` + `tick_id`; other calls return `returns`) · Kritazya: engine tests |
| `ai_tools/` | §4 tools `{tool, input, output}`: every read tool, `explain_decision`, every `propose_*` (output Proposal whose payload = input without `summary`), and the two bounded tools (`input_enum` lists the allowed values) | Suyog: `agent/tools.py` tests |
| `spacetime/` | `tables/<table>.json` rows (field names exactly as §5; `live_device.key` = `<lane>:<device_id>`, single-row tables `id: 0`, `live_tick.forecast_kw_json` keeps the latest forecast with `forecast_ts`), `reducers/<reducer>.json` `{reducer, args}` (the HTTP JSON args array), `rows_stream.jsonl` = the `publish_ticks` payload per tick (object form; the reducer arg is its JSON string) | Ashirwad: mock live hook replays `rows_stream.jsonl` and seeds the other tables · Kritazya: `fakes/fake_live.py`, `spacetime/seed.ts` |
| `convex/` | `tables/<table>.json` documents (no `_id` / `_creationTime`), `functions/<fn>.json` `{function, type, args, returns}` for every §6 function | Suyog: `store/` memory fallback seed, Convex tests |
| `agents/` | §7 request/response models (`region: "caiso_np15"`), `agent_log.jsonl` (kinds request/response/post), `context_post.json` (the periodic POST /api/context) | Suyog: agents `--recorded` mode |
| `scenario/demo_cafe/` | `scenario.json`, `index.json` | everyone |
| `MANIFEST.json` | file → contract section → consumers → seam | everyone |

## Conventions
snake_case; units in names; ISO 8601 UTC with `Z`; ids `<type_id>_<n>`, `d_0001`, `c_0001`, `e_0001`, `p_0001`,
`s_0001`, `k_01`, `run_0001`, `chat_0001`. Labels: devices/hub `simulated` (one `measured` device in `shapes/` only),
context `recorded`, tariff `illustrative`, explanations `template`. Catalog power values are placeholders
(`source_note: "PLACEHOLDER"`); catalog `params` follow §1 per power model (the cycling duty values are what the toy physics implies).
Forecasts are the scripted plan re-simulated with what was known at that tick (no peeking at the surge before it was
requested); they stand in for the real forecaster.
