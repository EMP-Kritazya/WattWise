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
| Dataset id / file | |
| County | |
| Timestamp zone + convention | |
| Electricity column names used | |

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
- **Until the ComStock extract exists:** the fixture builder's fake 2-month history (`contracts/fixtures/history/`, 2026-05-17 →
  2026-07-17 17:30 local, `source: fixture_synthetic`, `label: simulated`) stands in, in the same `WarmUpHistory` shape. Its
  fake June/July `BacktestResult` (`rest/get_backtest.json`) is for building the Proof screen only; it is never shown as savings.

## Distributing historical load onto devices (engine code, never AI)
A fixed recipe. Same input → same output. Devices always sum to the original value exactly.

**Step 1 — total → categories**
- ComStock: already split (end-use columns).
- Real meter (total only): apply ComStock's category shares for that hour of day as a template, scaled to the real total.

**Step 2 — category → devices** using fixed shares per device (from rated power × typical duty cycle).

Example, one 15-min interval, total 50 kW:
| Category | Share | kW | Devices |
|---|---|---|---|
| Refrigeration | 30% | 15.0 | walk-in 7.5 · reach-in 4.5 · ice machine 3.0 |
| Cooling | 25% | 12.5 | HVAC 12.5 |
| Cooking | 25% | 12.5 | oven 5.0 · fryer 5.0 · grill 2.5 |
| Water heating | 10% | 5.0 | water heater 3.0 · dishwasher 2.0 |
| Lighting | 10% | 5.0 | lights 5.0 |
| **Total** | | **50.0** | sums exactly |

Shares and windows are **assumptions**: keep them in `backtest/assumptions.yaml` with ids
(`base`, `low_flex`, `heavy_equipment`, `bad_forecast`).

## Replay and backtest
- The replay feeds the kitchen one 15-min row at a time → no peeking by construction.
- Replay step = 15 minutes; the decider runs on **every** step (live mode runs it every 5 sim minutes).
- First 4 weeks = warm-up history, not scored (the forecaster and the `minimize` target both use the previous 4 weeks).
  So **January is scored from day 29 and labeled "partial"** on the Proof screen. "All 12 months" means 11 full months + partial January.
- Run each month three ways through the **same** loop and bill them with the **same** tariff function:

| Policy | What it does |
|---|---|
| `without` | Every device exactly as in the data |
| `timer` | Best fixed daily schedule for deferrable jobs, chosen on the **previous** month (a fair, strong baseline). January has no previous month, so its timer is fitted on the warm-up weeks |
| `with` | The WattWise engine; escalations resolved by the **default** (no Claude), so results are reproducible and conservative |

Context in replay: historical weather (Open-Meteo archive) and prices (CAISO history) for the same dates, labeled
`real_measured`; crowd effect `none`. Optional, cut item: one replayed week with Claude resolving escalations, shown separately.

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
