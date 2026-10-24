# Design: Data and proof (owner: Kritazya)

Goal: show, on historical data, what WattWise would have saved — fairly, reproducibly, honestly.

## Data
| Use | Source | What it is |
|---|---|---|
| Main replay | NREL ComStock End-Use Load Profiles (data.openei.org; viewer comstock.nrel.gov) | 15-min, full-year load for full-service restaurants, split by end use. **Calibrated model data**, not one restaurant's meter. |
| Real-meter check (optional) | Building Data Genome 2 (github.com/buds-lab/building-data-genome-project-2) | **Real** hourly whole-building meters, 2016–2017, filter primary use = food service. Often campus dining. |
| Tariff | OpenEI Utility Rate Database | One **real, named** commercial tariff with demand charges (e.g. a PG&E rate). Record the id in DECISIONS.md. |
| Equipment power | FSTC test reports, ENERGY STAR specs | Rated/idle power for the equipment catalog |

Loading rules: electricity columns only · ComStock timestamps are EST → convert to UTC, display in America/Los_Angeles ·
energy per 15 min → `power_kw = kwh × 4` · verify column names at download and record them here.

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
- First 3 weeks = warm-up history, not scored.
- Run each month three ways through the **same** loop and bill them with the **same** tariff function:

| Policy | What it does |
|---|---|
| `without` | Every device exactly as in the data |
| `timer` | Best fixed daily schedule for deferrable jobs, chosen on the **previous** month (a fair, strong baseline) |
| `with` | The WattWise engine |

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
12-month table · busiest-day chart · sensitivity table · cached results for the Proof screen.

## Labels (use exactly)
"DOE-calibrated restaurant profile (NREL ComStock)" · "Real metered food-service building (BDG2)" · "Simulated".
Never "a real restaurant's bill".
