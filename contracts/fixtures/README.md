# contracts/fixtures — shared fake data

**FAKE DATA — not measured, not live.** Every number comes from `generate.py`: a toy simulation of the Demo Café (customers +
appliance physics, standing in for `frontend/src/sim`) and a toy rule-following controller for the `with` lane (standing in for
the engine, whose internals are TBD). They are illustrative values, not engine output. Bill and backtest numbers are invented and
must never be shown as savings (`backtest-auditor` rule).

Owner: Kritazya. Changes go by PR. Built by the `fixture-builder` subagent from `docs/CONTRACTS.md`, validated against the
Pydantic models in `backend/contracts/`. Readings the fixtures had to choose are in `GAPS.md`.

## Regenerate and check
```
python3 contracts/fixtures/generate.py                    # seed 42, stdlib only, identical bytes on every run (~7 s)
python3 contracts/fixtures/check.py                       # everything below + determinism + Pydantic via backend/.venv (~25 s)
python3 contracts/fixtures/generate.py --days 7 --out /tmp/run7   # every tick of a 1..7-day run (not committed)
cd backend && .venv/bin/python -m contracts.check_fixtures --verbose   # the shape-only validator
```
Never hand-edit a JSON file: change `generate.py`, regenerate, run `check.py`. `CHECK_QUICK=1` skips the Pydantic and
regeneration passes for local iteration only.

## One run, three views
Tick *n* is the simulated minute starting at `2026-07-18T00:30:00Z + (n − 1) min` (Friday 17 July 2026, 17:30
America/Los_Angeles; UTC in data). The same physical run (same seed, same ids) feeds:
- **the evening scenario** (`scenario/demo_cafe/`, and the top-level `hub_protocol/`, `facade/`, `spacetime/`, `ws/` streams):
  ticks 1..120, 17:30–19:30, `run_days: 1`, every tick published;
- **the multi-day scenario** (`scenario/demo_cafe_multiday/`): segments of the run with `run_days: 2`, through day 2's close;
- **`generate.py --days N`**: every tick of an N-day run (N ≤ 7), for engine edge tests. `--days 2` equals the committed
  multi-day segments line for line (`check.py` verifies it).

## The evening (Demo Café, `scenario/demo_cafe/`)
`peak_mode: "cap"` at 40 kW (Meter `target_kw` 40), tariff `demo_tariff_v1` (`illustrative`, 2026-10-24 shape: demand
`windows` list + `months` + `days`, energy `months` + `days`, `fixed_charges: []`): the evening is in the 16:00–21:00 peak
period, so energy is $0.38/kWh and both demand charges ($20/kW month max, $8/kW peak-period max) apply. Every Meter carries
`demand_peaks` (one per charge applying this month, tariff order, `cost_usd = usd_per_kw × peak_kw` on the published peak);
`live_tick.demand_peaks_json` is that list as a string. HVAC is the catalog's 8.0 kW unit (two of them); the toy dining-room
load is in kW, so each unit runs at a higher duty and never draws more than 8.0 kW (`check.py` asserts it, history included).
- **Warm-up:** both lanes start from `history/warmup_demo_cafe.json` (`month_to_date: null`), so the first Meter continues the
  month the engine metered from the July history blocks: month peak 42.54 kW (Saturday 11 July party night), 247.8 kWh today
  before 17:30. `check.py` recomputes it from the history.
- **Context:** recorded (hot evening, high grid prices, Giants game from `demo_events`, crowd `medium`) posted at tick 1 and
  refreshed at tick 61; later posts every 300 sim min (`scenario.json.context_post_ticks`). `sim_tick.inputs` copies the context
  in force, which copies `history/daily_inputs.json`.
- **Surge:** `request_surge(40, 60)` at tick 30, delivered once in `sim_tick` 31 (`s_0001`).
- **Engine moves** (`with` lane, decision ticks only, `reason_code: stay_under_cap` / `catch_up`): holds of the ice machine
  and dishwasher, reductions of HVAC, water heater and walk-in, each ≤ 30 min, 30-min cooldown, restored at the limit.
- **Escalation `e_0001`** opens at tick 50 (18:20) for the 18:45 block (forecast 40.7 kW after every in-rules move). Options:
  `accept_overrun` (0.7 kW over, within authority, rank 1), `extend_delay_dishwasher` (5 min past its deadline and
  `max_delay_min`, within authority, rank 2), `deep_reduce_water_heater` (20 % below `min_power_pct`, outside, rank 3). The fallback (rank 1, `accept_overrun`) is in force from the step it opens (no Commands to issue). Claude is
  offered every ranked option with `within_authority` (`ai_tools/choose_escalation_option.json` `input_enum`) and
  answers between ticks 50 and 51 with the same option → `resolved`, no extra command. The clock never slows.
- **Owner click:** after tick 118 the owner presses "start dishwasher" while it runs in both lanes: `owner_command` on both
  lanes (without first), `owner_override` decisions `d_0014`/`d_0015` in step 119, both acks `ok: false, job_running` in tick 120.
- **Result at 19:30:** without lane month peak 47.71 kW (a new July peak), with lane 42.54 kW (unchanged; its only block over
  40 kW is the escalation's 18:45 block at 40.38 kW, inside the accepted 0.7 kW); saved today $147.47, peak avoided 5.17 kW.
  Tick 120 issues one restore (`c_0018`) that is delivered in tick 121, outside the evening files.

## The multi-day run (`scenario/demo_cafe_multiday/`, `run_days: 2`)
| Segment | Ticks | Phase | Published |
|---|---|---|---|
| Fri 21:30 → 22:00 close | 241–270 | `service`, day 1 | every tick |
| Fri 22:00 → Sat 10:00 | 271–990 | `overnight` (`fast_forward: true`, `is_open: false`) | hub + step stream every tick; `rows_stream`, ws `tick`/`comparison`/`clock` and `clock_stream` once per closed 15-min block |
| Sat 10:00 → 13:30 (open, lunch, `s_0002` +35 at 12:15) | 991–1200 | `service`, day 2 | every tick |
| *gap* | 1201–1695 | — | omitted to keep the size down (they are in `--days 2`) |
| Sat 21:45 → 22:00 close | 1696–1710 | `service`, day 2 | every tick |
| after 22:00 | — | `closed`, `paused_reason: run_complete`, `playing: false` | final clock |
Local midnight is tick 391: `energy_kwh_today` / `cost_usd_today` restart from that minute; month counters continue. Overnight
the kitchen draws refrigeration, ice machine and water-heater standby, 10 % night lighting, cooking off 15 min after close and
preheating 30 min before open, HVAC setback (+4 °C). `day_index` goes 1 → 2 at the 10:00 open. The streams start with the clock
and the context in force at tick 240; commands across the gap are not visible. Files: `server_to_hub.jsonl`,
`hub_to_server.jsonl`, `step_stream.jsonl`, `rows_stream.jsonl` (publish_ticks payloads), `ws_stream.jsonl`,
`clock_stream.jsonl` (`set_clock` args), `scenario.json`, `index.json` (segments, ids, midnight and open ticks).

## History (`history/`, G59)
- `warmup_demo_cafe.json` — a `WarmUpHistory` (`fixture_synthetic` / `simulated`, `dataset_id: fixture_synthetic_demo_cafe_v1`,
  `scale: 1.0`, `day_offset: 0`, `month_to_date: null`): 15-min `avg_kw` (3 decimals) for each of the 12 devices, 2026-05-17
  00:00 → 2026-07-17 17:30 local (71,112 blocks, sorted by time then roster order, every block ends ≤ `end`). It is the same toy
  simulation running uncontrolled: open 10:00–22:00, lunch and dinner rush, weekends busier, a June heat wave, one event night
  (Fri 26 June, Giants game), three booked parties, refrigeration cycling all night, lights 10 % when closed. Monthly peaks: May
  41.99, June 42.68, July (to the 17th) 42.54 kW; the Friday `minimize` target from the 4 previous Fridays is 39.7 kW. No block
  exceeds its device's `rated_kw` (HVAC ≤ 8.0 kW).
- `daily_inputs.json` — per local day (2026-05-17 … 2026-07-23 = history + 7 live days): hourly outdoor temperature and grid
  price, price stress, `crowd_effect`, events, scheduled surges (with `surge_id` on live days), plus the customer profile and
  weekday factors. Fixture-only (no contract shape). `check.py` verifies every `sim_tick.inputs` and context post against it.
- `rest/get_backtest.json` (+ `facade/run_backtest.json`, `shapes/backtest_result.json`, Convex `backtest_results`): fake
  `BacktestResult` for 2026-06 (`partial: false`) and 2026-07 (`partial: true`, to the 17th 17:30) — the history billed on
  `demo_tariff_v1` (`without`, equal to a raw re-bill), a fixed timer for jobs, and a toy replay plant for `with` (energy
  conserved, 0 rule violations); `saved_usd` = without − with, `saved_vs_timer_usd` = timer − with, every Bill with
  `fixed_usd` (0 on this tariff). Dataset label: "Simulated fixture data … not ComStock, not a measured bill". Never present
  it as savings.
- Proof chart running line: one `BacktestPoint` per local day (47: June 1–30, July 1–17), in
  `facade/run_backtest_on_progress.jsonl` (the `on_progress` events in contract order: a point per day, the month at its
  end, progress at each quarter of a month; FakeKitchen replays them), `spacetime/tables/backtest_point.json` /
  `backtest_month.json` (rows of `run_0001`), `ws/backtest_point.json` / `ws/backtest_month.json`. The last point of each
  month equals that month's `saved_usd` to the cent (`check.py` asserts it). The July 17 point is stamped at the end of the
  local day although the history stops at 17:30.
- `shapes/backtest_inputs.json` (= `facade/run_backtest.json` `args.inputs`): `BacktestInputs` with the Demo Café config,
  `demo_tariff_v1`, the catalog, seed 42, `base` assumptions and a **3-day series excerpt** (June 1–3, the fixture history,
  `fixture_synthetic` / `simulated`) to keep the file small; the real series covers the 4 warm-up weeks + every replayed
  month. The facade file says so in its fixture-only `note`.
- `shapes/tariff_pge_b19.json`: PG&E B-19 Secondary Voluntary (`label: "urdb"`, URDB `69de8cdb02f684104e01267d`) in the
  Tariff shape: `max_demand` $37.37 all months · `peak_demand_winter` months 1–5, 10–12, 16:00–21:00, $2.31 ·
  `peak_demand_summer` months 6–9, 16:00–21:00, $46.16 · `part_peak_demand_summer` months 6–9, 14:00–16:00 + 21:00–23:00,
  $10.52 · six energy prices by season in nine entries (wrap-around `end` < `start` where the period crosses midnight;
  spring super-off-peak 09:00–14:00) · `customer_charge` $11.36882 per **day** (URDB `fixedchargeunits: "$/day"`). Values
  unchanged from URDB (embedded in `generate.py`; `check.py` re-derives every hour of every month from
  `dataset/tariffs/…69de8cdb….json` when that gitignored file is present). Not used by the Demo Café run.

## Files and who loads them
| Folder | What | Consumed by |
|---|---|---|
| `shapes/` | One example per §1 shape. Variants: kitchen_config cap + `_minimize`; hub_report/tick_state with + without (tick 50 / the escalation tick); command (engine) + `command_owner` (standalone owner reduce 10 %) with `decision_owner_override`; acks ok / clamped (`out_of_range`) / rejected (`job_running`, from the stream); escalation open / resolved_claude / rejected_claude / expired_default / obsolete (alternative outcomes of `e_0001`; only `resolved` happens in the stream); `warning_cap_unreachable` (illustrative: what a 30 kW cap would trigger at 18:20); `warm_up_history` (the last block of the history); one Proposal per kind; `tariff` (demo) + `tariff_pge_b19` (URDB); `backtest_result` / `backtest_point` / `backtest_inputs` | everyone (generated types, tests) |
| `history/` | Fake 2-month warm-up + daily inputs (above) | Suyog: runtime `warm_up(history)` until ComStock · Kritazya: engine warm-up, forecaster, backtest · Ashirwad: Proof screen |
| `hub_protocol/` | §8 messages, one file per type (+ `sim_tick_replay`, `sim_tick_overnight`), `server_to_hub.jsonl` (hub_welcome, sim_build, 120 sim_ticks), `hub_to_server.jsonl` (hub_hello, 120 hub_reports) | Ashirwad: `src/mocks/mockHubServer.ts` plays `server_to_hub.jsonl` · Suyog: `fakes/fake_hub_client.py` answers each `sim_tick` with the matching `hub_to_server` line · Kritazya: HubReports as engine input |
| `rest/` | One file per §2 endpoint `{method, path, status, request, response}` + `_422`/`_404` examples (incl. `post_sim_control_next_day`, `post_sim_control_422`, `post_decision_undo_422`) | Ashirwad: `src/mocks` REST handlers · Suyog: API tests |
| `ws/` | One file per `/ws` message + `stream.jsonl` (clock, context, agent_log, then per tick: ticks, comparison, decisions, escalations, Claude's answer) | Ashirwad: `/ws` fallback mock · Suyog: API tests |
| `facade/` | §3 calls `{call, args, returns}` (`raises` on the rule-error files, `note` on `run_backtest.json`); `run_backtest_on_progress.jsonl` (on_progress events); `warm_up.json` embeds the full history; `snapshot.json` has every §3 key (with lane after tick 120); `step_stream.jsonl` per tick and lane `{args: {minutes, hub_report}, returns: TickState}` | Suyog: `fakes/fake_kitchen.py` (look up `step` by lane + tick_id) · Kritazya: engine tests |
| `ai_tools/` | §4 tools `{tool, input, output}`; the two bounded tools list `input_enum` | Suyog: `agent/tools.py` tests |
| `spacetime/` | `tables/<table>.json` (incl. `backtest_point` / `backtest_month`), `reducers/<reducer>.json` (`set_clock` 9 args, `publish_backtest_point`, `publish_backtest_month`, `reset_backtest`), `rows_stream.jsonl` (publish_ticks per tick) | Ashirwad: mock live hook · Kritazya: `fakes/fake_live.py`, `spacetime/seed.ts` |
| `convex/` | `tables/<table>.json`, `functions/<fn>.json` | Suyog: `store/` memory seed, Convex tests |
| `agents/` | §7 request/response models, `agent_log.jsonl`, `context_post.json` | Suyog: agents `--recorded` |
| `scenario/` | `demo_cafe/` (evening: `scenario.json` timeline + `index.json` ids) · `demo_cafe_multiday/` (above) | everyone |
| `MANIFEST.json` | file → contract section → consumers → seam | everyone |

## Conventions
snake_case; units in names; ISO 8601 UTC with `Z`; ids `<type_id>_<n>`, `d_0001`, `c_0001`, `e_0001`, `p_0001`, `s_0001`,
`k_01`, `run_0001`, `chat_0001` (one shared counter per type across lanes; standalone examples use ids after the last id of the
multi-day run). Labels: devices/hub `simulated` (one `measured` device in `shapes/` only), context `recorded`, tariff
`illustrative` (B-19 example `urdb`), history and backtest `simulated`, explanations `template`. The catalog is Ashirwad's `backend/data/equipment_catalog.json`
(embedded verbatim in `generate.py`; its `source_note`s state the demo assumptions behind each rated value).
Forecasts are the toy plan re-simulated from the lane's current state with what was known at that tick (no peeking at a surge
before it was requested).
