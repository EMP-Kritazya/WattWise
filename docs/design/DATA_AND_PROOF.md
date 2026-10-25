# Design: Data and proof (owner: Kritazya)

## Principles
Same data, tariff and loop for every policy · no peeking · all 12 months (January partial) · strong timer baseline ·
worst case shown · Claude never in the scored backtest · exact labels.

Goal: show, on historical data, what WattWise would have saved — fairly, reproducibly, honestly.

## Data
| Use | Source | What it is |
|---|---|---|
| Main replay | NREL ComStock End-Use Load Profiles (data.openei.org; viewer comstock.nrel.gov) | 15-min, full-year load for full-service restaurants, split by end use. **Calibrated model data**, not one restaurant's meter. |
| Real-meter check (optional) | Building Data Genome 2 (github.com/buds-lab/building-data-genome-project-2) | **Real** hourly whole-building meters, 2016–2017, filter primary use = food service. Often campus dining. |
| Tariff | OpenEI Utility Rate Database | One **real, named** commercial tariff with demand charges (e.g. a PG&E rate), in the CONTRACTS.md Tariff shape (`label: "urdb"`). Until chosen, everything uses the made-up `demo_tariff_v1` (`label: "illustrative"`); no savings number from it is ever shown as real. |
| Equipment power | FSTC test reports, ENERGY STAR specs | Rated/idle power for the equipment catalog |

Loading rules: electricity columns only · energy per 15 min → `power_kw = kwh × 4` · verify column names at download
and record them here.

**Region and time zone (check before anything else).** Pick the ComStock county in the **same region as the tariff**
(a California county for a PG&E rate) so the lunch rush lands at the right local hour against the tariff's time-of-use
windows. Check and record the dataset's timestamp convention (zone, standard vs daylight time, interval start vs end).
Convert to UTC inside; display in the restaurant's local zone (America/Los_Angeles for a California county).
Record dataset id, county and convention in the table below.

| Field | Value (fill at download) |
|---|---|
| Dataset id / file | NREL ComStock `comstock_amy2018_release_3`, upgrade 45 "Electric Kitchen Equipment", `bldg_id 5847` (full-service restaurant, 2,000 ft², 52.0 kW peak, 251 MWh/yr); file `dataset/comstock/timeseries/5847-45.parquet` (gitignored), 35,040 rows; loader `backend/data/comstock.py` |
| County | San Francisco County, `G0600750` (PG&E territory, CEC climate zone 3); weather year 2018 (AMY, Oakland airport) |
| Timestamp zone + convention | **Local standard time all year (UTC−8, no DST in the stamps), interval-ending** (first row `2018-01-01 00:15:00`, last `2019-01-01 00:00:00`, no gaps). UTC interval start = `timestamp − 15 min + 8 h`. Verified 2026-10-24: the dinner peak moves 20:30 → 19:30 standard time when DST starts (11 Mar 2018) and back after 4 Nov, so the building follows the wall clock (tested in `tests/data/test_comstock.py`) |
| Electricity column names used | `out.electricity.{cooling,fans,heating,pumps,heat_rejection,heat_recovery,interior_equipment,interior_lighting,exterior_lighting,refrigeration,water_systems,pv,total}.energy_consumption` (kWh per 15 min, `kW = kWh × 4`); refrigeration, water_systems and pv are 0 for bldg 5847 (the loader raises otherwise) |
| Calendar (`day_offset`) | **2919 days** (417 weeks): 2018-01-01 (Mon) → 2025-12-29 (Mon). It also maps the 2018 DST switches onto the 2026 ones (11 Mar → 8 Mar, 4 Nov → 1 Nov), so the wall-clock schedule is kept exactly. Replay calendar 2025-12-29 … 2026-12-28: January 2026 is partial (warm-up = first 28 days, scored 26–31 Jan) and **December 2026 is partial too** (1–28 Dec, the data ends) |
| Tariff | PG&E B-19 Secondary Voluntary, URDB `69de8cdb02f684104e01267d` (`label: "urdb"`), converted by `backend/data/tariff_urdb.py` (equals `contracts/fixtures/shapes/tariff_pge_b19.json`, tested) |
| Recipe values | `backend/backtest/assumptions.yaml` (step 1 mapping, two-part step 2: `base_duty` + `variable_shares` from appliance-split §3, Demo Café roster and hours, sensitivity ids) |

## Real data in the live product (not only on the Proof screen)
The same ComStock restaurant and the same URDB tariff feed the live demo, so the live kitchen is "today" in a real, calibrated
month rather than a cold start. One dataset, one tariff, four places:

| Where | How | Label on screen |
|---|---|---|
| **Live bill** | Once the URDB rate is chosen it replaces `demo_tariff_v1` in `Kitchen(config, tariff)` for the live run *and* the backtest, so every live $ is on a real, named rate | tariff name + `urdb` |
| **Warm-up = "the restaurant's last 4 weeks"** | `backend/data/warmup.py` builds `WarmUpHistory`: the 4 weeks before the scenario start, from ComStock, scaled to the Demo Café (`scale`) and spread onto its devices by the recipe below. The forecaster's weekday × time-of-day curve and the `minimize` target (highest peak of the previous 4 same weekdays) come from it | `calibrated_model` |
| **Month to date** | The engine meters the history days of the current month on the tariff, so the run starts with a real-shaped month peak and cost: a lunch spike earlier in the month has already set a demand charge, and tonight the engine must not beat it | `calibrated_model` |
| **The pitch's "Pain" beat** | Last month's `without` Bill from the backtest: the one 15-min block that set the demand charge, in $ (after `backtest-auditor`) | `calibrated_model` + `urdb` |

Rules for the live use:
- **Calendar alignment.** ComStock is one weather year (record it below); the sim calendar is 2026. `day_offset` = the whole number of
  days (a multiple of 7) that maps the dataset year onto the sim dates with weekdays aligned (e.g. sim Fri 17 Jul 2026 ↔ the dataset's
  nearest Friday in mid-July). One offset for the whole window. Holidays in the dataset are kept, not hidden.
- **Scale.** `scale` = Demo Café reference peak ÷ ComStock building's peak for the same month (kept in `assumptions.yaml` as `live_scale`),
  applied before the device recipe. The live ratio (ENGINE.md section 3) absorbs the remaining gap between the sim and the history.
- **Region.** The demo kitchen is in the Marina, San Francisco: pick the ComStock county and the URDB rate in PG&E territory
  (e.g. San Francisco County + a PG&E commercial rate with a monthly and a peak-period demand charge, which the Meter's
  `month_peak_kw` / `on_peak_month_peak_kw` already model).
- **Files.** The raw dataset stays out of git (`data/`, gitignored); `warmup.py` reads a processed per-device extract built once by
  `python -m data.build_warmup` (also in the backend image build). Missing file → the engine runs without warm-up; nothing blocks.
- **Honesty.** Warm-up and month-to-date are a calibrated model of a restaurant, never "your past bill"; the live tick-by-tick load is
  `simulated`.
- **Until the ComStock extract exists:** the fixture builder's fake 2-month history (`contracts/fixtures/history/`, from its next run; 2026-05-17 →
  2026-07-17 17:30 local, `source: fixture_synthetic`, `label: simulated`) stands in, in the same `WarmUpHistory` shape. Its
  fake June/July `BacktestResult` (`rest/get_backtest.json`) is for building the Proof screen only; it is never shown as savings.

## Distributing historical load onto devices (engine code, never AI)
A fixed recipe. Same input → same output. Devices always sum to the original value exactly.

**Step 1 — total → groups** (revised 2026-10-25, appliance-recheck.md)
- ComStock: already split (end-use columns). **hvac = `cooling` + `heating` + `pumps` + `heat_rejection` + `heat_recovery`**
  → split equally over the `hvac` units (bldg 5847: only cooling is non-zero; worst block 9.974 kW at 2018-06-23 18:30 PST =
  4.987 kW per unit, under the catalog's 5.0 kW). **exhaust = `fans`** (a constant 5.739 kW all year, `night_fanon_vent`) →
  `kitchen_exhaust` (rated 5.74). **lights = `interior_lighting` + `exterior_lighting`** → `lights` (max 1.58 kW, rated 1.6).
  `interior_equipment` (+ the file's float32 residual) → step 2. refrigeration, water_systems and pv must be 0 (the loader raises).
  Every device row sums exactly to the dataset's `total` for that row; the baseline is never altered.
- Real meter (total only): apply ComStock's category shares for that hour of day as a template, scaled to the real total.

**Step 2 — interior_equipment → devices, two-part** (decided 2026-10-25; `backend/data/recipe.py`)
1. **Base:** refrigeration draws its duty average, `rated_kw × duty`: the catalog's busy/idle midpoint while the kitchen is open
   and its idle duty while closed (walk-in 2.0 kW × 50 / 33 %, reach-in 0.6 × 32.5 / 20 %, freezer 0.7 × 52.5 / 40 %), and the
   ice machine 1.2 kW × 60 % (ASSUMPTION). In a row where interior_equipment is smaller (overnight it is 0.7 kW), all base
   devices are scaled down together; the data never gets more energy.
2. **Variable rest** (interior_equipment − base) by energy shares from appliance-split §3's daily kWh model: fryer 6.6,
   oven 8.2, grill 13.8, dishwasher 5.5, water heater 17.1 %, and **other_equipment 48.8 %** (always_on plug and process load:
   holding cabinets, steamer, steam table, warmers, microwaves; the 205.7 kWh/day no catalog device explains). Its rated_kw 16.4
   is this recipe's residual peak (16.30 kW) rounded up.

No device exceeds its catalog `rated_kw` anywhere in the year (a test replays the whole year; the loader raises, never clips).
The backtest kitchen keeps **09:00–24:00** hours (the live Demo Café keeps 10:00–22:00): ComStock 5847 is busy from 09:00 to
02:00, and a 22:00 close would put the close-time rules inside the data's dinner service. A close after midnight is not in the
contract, so 24:00 is the closest.

Shares, duties and hours are **assumptions**: they live in `backtest/assumptions.yaml` with ids
(`base`, `low_flex`, `heavy_equipment`, `bad_forecast`, and `zero_flex` for the zero-flexibility check).

## Replay and backtest
- The replay feeds the kitchen one 15-min row at a time → no peeking by construction.
- Replay step = 15 minutes; the decider runs on **every** step (live mode runs it every 5 sim minutes).
- First 4 weeks = warm-up history, not scored (the forecaster and the `minimize` target both use the previous 4 weeks).
  So **January is scored from day 29 and labeled "partial"** on the Proof screen. "All 12 months" means 11 full months + partial January.
- Bills and BacktestPoints cover **scored blocks only** (2026-10-24, `engine/replay.py`): January's mark is the bill of 26–31 Jan,
  billed by `engine.meter.MonthBill` from the HubReports each lane's Kitchen metered (the Meter `cost_usd_month` definition,
  3-decimal peaks). The last point of a month equals its mark to the cent by construction.
- Run each month three ways through the **same** loop and bill them with the **same** tariff function:

| Policy | What it does |
|---|---|
| `without` | Every device exactly as in the data |
| `timer` | Best fixed daily schedule for deferrable jobs, chosen on the **previous** month (a fair, strong baseline). January has no previous month, so its timer is fitted on the warm-up weeks |
| `with` | The WattWise engine; escalations end with the engine's **fallback** (no Claude), so results are reproducible and conservative |

Context in replay: historical weather (Open-Meteo archive) and prices (CAISO history) for the same dates, labeled
`recorded` (historical archives); crowd effect `none`. Optional, cut item: one replayed week with Claude resolving escalations, shown separately.

**Serving the replay** (`backend/runtime/backtest_runner.py`, 2026-10-25): `POST /api/backtest/run` answers with a `run_id`
at once and plays the run's `on_progress` events in order: `backtest_point` / `backtest_month` through the live port (SpacetimeDB
rows, or /ws messages), `backtest_progress` over /ws. A month takes `REPLAY_MONTH_S` real seconds (default 5, so the year plays in
about a minute); the pace is display only. The replay itself runs in a separate process (CPU-bound; a thread would starve the live
clock) at about 18 s per month, and the finished events are cached in `data/backtest_cache/proof_<fingerprint>.json`, keyed by the
catalog, assumptions, tariff and engine/data code. `BACKTEST_PRECOMPUTE=1` (default) fills that cache at startup, so the Proof
button plays at once; a press during the warm-up follows the computation as it goes. Without the dataset and without a cache the
request answers 422 with the reason.

## Checks (all must pass before a number is shown)
| Check | Expected |
|---|---|
| `without` bill vs. bill from raw data | equal to the cent |
| Daily energy, every policy | equal to original |
| Rule violations (always_on touched, deadline missed, flexible below min) | 0 |
| Zero-flexibility run | savings = 0 |
| No-peeking guard | never triggered |

## Sensitivity
Re-run with `low_flex` (half the flexibility), `heavy_equipment` (+20% draw), `bad_forecast` (±20% noise),
and 2 other real tariffs. Report the worst case next to the base case.

## Outputs
12-month table · busiest-day chart · sensitivity table · cached results for the Proof screen (file for `DEMO_MODE`)
· every BacktestResult saved to Convex `backtest_results`. No number is shown until `backtest-auditor` returns CLEARED.

## Labels (use exactly)
"DOE-calibrated restaurant profile (NREL ComStock)" · "Real metered food-service building (BDG2)" · "Simulated".
Never "a real restaurant's bill".
