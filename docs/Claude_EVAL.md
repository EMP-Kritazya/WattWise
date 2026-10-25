# Claude Code Prompt — Design a Complete WattWise Evaluation Framework

You are working in the WattWise repository. **Your task is to author a comprehensive, implementation-ready `EVAL.md` specification** for evaluating the WattWise restaurant energy optimization engine and its HVAC planning model. Do **not** implement the framework yet unless I explicitly ask. The document should be detailed enough that another coding agent can implement it independently with minimal questions, and that a hackathon judge can understand what was evaluated and why.

> **Already decided (2026-10-24; ENGINE.md, CONTRACTS.md, Main_Gaps.md):** `reduce` % is of `rated_kw`; this build has no HVAC
> thermal model (`max_indoor_temp_change_c` is null), so the HVAC-model parts are a later phase; escalations apply a harm-ranked
> fallback at once and Claude may switch it. Treat these as settled, not `DECISION REQUIRED`.

## 0. Read the repository before writing

First inspect `ENGINE.md`, `CONTRACTS.md`, `KRITAZYA.md`, `DEMO.md`, equipment catalog, relevant backend engine modules, hub protocol fixtures, simulation code, existing tests, and any existing eval/backtest or data ingestion code. Identify what exists, what is proposed, and what is TBD. **Do not invent implemented functions, files, schemas, data sources, or performance results.** Use the repository's actual paths and contract field names. When a design choice is not settled, propose a default, explain its rationale, and mark it `DECISION REQUIRED` rather than silently treating it as agreed. Respect the engine's no-I/O, no-wall-clock, no-Claude-call boundary.

## 1. Document purpose and scope

Start `EVAL.md` with a one-paragraph executive summary and a concise definition: an _eval_ is a reproducible test protocol (scenarios + strategies + metrics + assertions + analysis), not merely a graph. Distinguish:

1. **Deterministic engine correctness tests** (hand-computed unit/contract tests, safety invariants).
2. **Closed-loop policy benchmarks** (baseline vs optimizer across the same exogenous scenario, with commands changing appliance states).
3. **HVAC model validation** (planning model prediction versus an independent simulation/observed trace; avoid circular self-validation).
4. **Robustness and sensitivity tests** (parameter uncertainty, forecasts, missing context, edge cases).
5. **Optional AI/Claude escalation evals** (agent decisions and authority/tool-use, kept separate from engine policy metrics).

Clarify that simulated results are **estimated**, not measured restaurant savings, and that the document is a build plan rather than a claim of completed evaluation.

## 2. Architecture and boundaries

Specify a concrete data flow, with a Mermaid diagram and ownership table:

`Scenario + seeded historical/context data -> independent evaluation runner -> simulation/hub model -> HubReport -> Kitchen.step(...) -> TickState.new_commands -> next simulated tick -> new HubReport`, with metric collection, traces, assertions, artifacts, and reporting outside `engine/`.

State that the engine is pure Python, consumes structured inputs, produces decisions/commands/escalations, and never directly drives the browser, accesses the network, or writes files. The eval runner may perform I/O. Ensure the baseline and optimized lanes see the **same external conditions** but maintain separate internal device/thermal states. Avoid replaying an immutable power trace after issuing commands (that would make the comparison invalid). Describe how to use the existing browser physics, a ported deterministic simulation model, or an independently implemented test plant; compare the tradeoffs and recommend the most feasible option for independent backend tests. Explain model mismatch and how to avoid sharing identical equations/parameters between the controller predictor and its only evaluator.

## 3. Exact scenarios and experimental matrix

Define reproducible scenario manifests with explicit types, units, timezone, simulated timestamps, seeds, restaurant configuration, appliance catalog version, tariff, weather, occupancy/customer traffic, initial indoor temperature, initial device states, queued jobs/deadlines, month-to-date peak and energy, warm-up history, context freshness, operating hours, and simulation length.

Design a **minimum viable benchmark** and an **extended benchmark**. Include at least:

- Weather: mild, hot, extreme heat (with actual temperature profiles, not just labels).
- Customer traffic: quiet, normal, dinner rush (with deterministic time-varying multipliers and appliance-job arrivals).
- Building/HVAC: efficient vs inefficient envelope; different thermal mass, cooling capacity, HVAC rated kW and COP/efficiency; single vs two HVAC units if supported.
- Tariff: flat energy-only, energy + monthly demand charge, TOU + demand charge; use explicitly illustrative demo tariffs unless verified tariff data is available.
- Monthly peak states: existing peak below, near, and above the forecast evening peak.
- Constraints: tight vs relaxed comfort range, minimum power, max reduction duration, owner override, food-safety floor, deferrable-job deadline.
- Failures/uncertainty: stale weather, missing history, wrong forecast, hub command clamping/rejection, delayed command acknowledgments, missing reading, escalation timeout.

Specify a manageable smoke-test subset that runs quickly, and a larger batch benchmark. Show the full scenario-by-strategy count formula, estimate runtime/storage, and explicitly avoid claiming any runs have occurred. Use paired experiments: same scenario and random seed across all strategies, independent state resets per run. Add a held-out scenario split for final evaluation to reduce overfitting.

## 4. Strategies and ablations (fully specified)

Provide a strategy matrix with precise policies, tunable parameters, validity conditions, and expected tradeoffs:

- **Unoptimized baseline:** no engine-driven load shifting; normal appliance behavior, same service requirements.
- **Fixed-rule baseline:** simple threshold/on-off or schedule policy, with safe bounds.
- **Conservative HVAC:** e.g. max 10% reduction from nominal, with comfort constraints.
- **Balanced HVAC:** e.g. max 25% reduction, with comfort constraints.
- **Aggressive HVAC:** e.g. max 40% reduction, still subject to absolute safety; record violations rather than hiding them.
- **Full WattWise:** deferrable jobs first, then flexible HVAC/refrigeration within rules, energy payback, 15-minute demand-aware planning.
- **Ablations:** no forecast, no demand charge awareness, no job shifting, no HVAC control, no context, no owed-energy ledger (diagnostic only; never treat invalid strategy as a deployable winner).
- **Optional oracle upper bound:** perfect future information, clearly labeled non-deployable benchmark.

Explain whether percentages refer to **rated power**, **current requested power**, or **available flexible range**, and choose one consistent interpretation. Ensure a 40% reduction does not imply bypassing safety/owner limits. Define whether each strategy is a configuration of the same engine or a separate controller implementation, and how strategy parameters are injected without changing the public contracts.

## 5. HVAC planning and evaluation models

Explain the first-order one-zone RC model, with equations, consistent units, timestep discretization, thermal resistance R, capacitance C, outdoor temperature, cooling output, internal gains, COP/efficiency, thermostat/deadband, minimum on/off duration, and how electric kW translates to cooling power. Include a worked numerical example with **clearly illustrative** parameter values and show how to compute `max_indoor_temp_change_c` over an option horizon **relative to the no-action counterfactual**. Clarify whether the metric is a signed change or maximum absolute/adverse temperature rise.

Define a distinct **evaluation plant** with either a higher-fidelity or intentionally perturbed model, or externally observed data if available; explain why evaluating the engine against its identical RC model is circular. Specify parameter calibration from equipment catalog and what must remain configurable. Explain job models (power, duration, earliest start, must-finish-by, interruptions) and cycling/refrigeration models with immutable food-safety floors. Include uncertainty sweeps and failure cases (heat wave, insufficient cooling, bad COP, high thermal mass, conflicting HVAC units).

## 6. Metering, billing, and energy accounting

Use `ENGINE.md` rules precisely: `energy_kwh += total_kw * minutes/60`, 15-minute **locally aligned** demand averages at :00/:15/:30/:45, monthly peak updates at completed blocks, TOU energy prices and tariff-defined demand components. Explain partial blocks, timezone/DST, day/month boundaries, and how warm-up/seeded monthly peaks affect savings. Never confuse peak instantaneous kW, 15-minute demand kW, kWh, and dollars. Define daily cost versus projected monthly bill and incremental demand charges; state that demand-charge reductions only accrue when the new monthly maximum is lower than the baseline's. Distinguish an avoided new peak from reducing a peak already set earlier in the month.

Define energy conservation for deferrable jobs and flexible loads, `owed_kwh`, payback deadlines, comfort recovery, terminal-state reconciliation, and the caveat that HVAC thermal efficiency can change total energy in reality; do not impose equality on physically different HVAC strategies without justifying the abstraction. Include explicit pass/fail tests for ledger closure and unmet work.

## 7. Metrics, formulas, units, and success gates

Define formulas, denominators, aggregation, sign conventions, and acceptance gates for:

- Peak demand avoided (kW and %), per completed 15-minute block and monthly max.
- Energy consumed (kWh), shifted (kWh), owed (kWh), unmet (kWh).
- Energy charges, demand charges, total projected bill ($), savings ($ and %), with tariff caveats.
- Comfort: maximum temperature, degree-minutes above comfort threshold, minutes outside band, worst `max_indoor_temp_change_c`.
- Safety: refrigeration floor violations, job deadline misses, owner-authority violations, forbidden always-on commands, command rejections, unacknowledged commands.
- Operational performance: number of commands, unnecessary oscillations, on/off cycles, escalations, owner interventions, unmet demand cap, forecast MAE/MAPE (careful at near-zero values), forecast bias.
- Planning-model accuracy: temperature MAE/RMSE, predicted vs realized peak, error calibration under parameter uncertainty.
- Reproducibility: determinism across repeated seeds, invariant/property tests, missing-data behavior.
- Optional Claude: escalation-choice validity, schema adherence, authorization compliance, explanation groundedness, latency, tool-call success, fallback behavior; **do not use LLM-as-judge as the sole authority for numerical/safety correctness**.

Separate **hard constraints** (food safety, unauthorized actions, impossible state transitions) from **soft objectives** (savings, comfort, command count). Define a scorecard that marks any hard-constraint violation as FAIL regardless of dollars saved; avoid a single opaque composite score. Define example thresholds as proposed defaults, not empirical facts.

## 8. Test plan with worked expected values

Carry forward the hand-computed cases from `ENGINE.md`, without silently changing them:

- Constant 40 kW for 60 minutes -> 40 kWh, four 15-minute blocks of 40 kW, monthly peak 40 kW.
- Dishwasher 6 kW for 30 minutes moved from overloaded blocks -> peak 46 to 40 kW, 3 kWh in both cases.
- HVAC 10 kW reduced to 6 kW for 15 minutes -> 1 kWh owed; later repaid.
- `compare_lanes`: $61.20 vs $42.80 -> $18.40 savings; 46 vs 40 kW -> 6 kW avoided.
- Cap-unreachable and authority escalation examples, including timeout/default.
- No-peeking future history, always-on untouched, refrigeration minimum, context crowd multiplier 1.25, command emitted exactly once.

Add property-based, metamorphic, integration, regression, boundary, and adversarial tests. Explicitly identify the current contract interfaces and fixtures to invoke, and any prerequisite stubs. Include a table: test ID, setup, expected result, assertion, test layer, and status (`specified`, `needs implementation`, `blocked by TBD`). Do not mark tests passed without executing them.

## 9. Dataset strategy and leakage prevention

Explain sources and limits: synthetic deterministic scenarios, published commercial-building simulations such as ComStock (building/end-use load profiles, **not necessarily appliance-level or measured restaurant data**), and real meter data only if actually available. Define an adapter to normalize external timestamps, units, building type, weather, load and end-use categories. Do not treat ComStock as live telemetry. Distinguish forecast training/history from held-out test periods, prevent reading timestamps >= simulation time, and explain how to initialize/warm up the meter without fabricating historical measured data. Document provenance, licenses, versions, missingness, and assumptions.

## 10. Execution plan and repository layout

Propose an implementation-ready directory tree under a dedicated eval area (e.g. `backend/evals/`), including scenario schema, scenario fixtures, strategy configurations, deterministic plant, runner, metrics, validators, artifacts, report generation, CLI, and tests. Reuse existing repo structure when present. Specify Python interfaces/pseudocode with types for `Scenario`, `StrategyConfig`, `EvalRun`, `EvalResult`, `Metrics`, `Violation`, and trace rows, without conflicting with `CONTRACTS.md`. Show exact proposed CLI commands such as `python -m ... --scenario ... --strategy ... --seed ...` and batch execution, but label commands **proposed** until implemented. Define file naming, run IDs, provenance metadata, reproducibility seeds, failure handling, timeouts, caching, and deterministic ordering. Specify CSV/JSON/Parquet outputs, plus a machine-readable summary and a human-readable report. Keep all eval file I/O outside `engine/`.

Provide an incremental build plan with dependencies and exit criteria:

**Phase 0:** contract audit and decisions; **Phase 1:** meter/rules unit tests; **Phase 2:** deterministic closed-loop plant; **Phase 3:** HVAC RC predictor and independent plant validation; **Phase 4:** strategy sweeps and metrics; **Phase 5:** robustness/held-out tests; **Phase 6:** charts and dashboard; **Phase 7 (optional):** Claude escalation evals. Assign relative priority P0/P1/P2 and estimate complexity (small/medium/large), not fictional hours.

## 11. Visualization and judge demo

Design a compact **Evaluation Lab** view for a judge with ~2 minutes:

1. Select scenario (hot Friday dinner rush, mild day, extreme heat).
2. Compare baseline, conservative, balanced, aggressive, and full WattWise.
3. Show a **cost-versus-comfort scatter plot** with failed policies visually distinguished.
4. Show 15-minute demand line chart with cap and baseline vs optimized.
5. Show cost breakdown (energy vs demand) and concise constraint pass/fail scorecard.
6. Allow viewing one real trace/decision explanation, with clearly labeled _simulated_ values and provenance.

Define the JSON response shape and frontend data flow for precomputed eval artifacts vs on-demand evaluation, without creating new public APIs unless necessary; if proposing an endpoint, mark it `PROPOSED` and document it for contract review. Explain how to prevent judges from mistaking illustrative charts for real evaluation output. Provide a 20–30 second pitch script and a truthful sample caption.

## 12. Risks, caveats, and explicit decisions

Create a `Risks & Caveats` section covering: circular validation, arbitrary HVAC parameters, lack of real restaurant calibration, tariff mismatch, 15-minute alignment, monthly demand charge nonlinearity, fake savings from dropped work, delayed command application, two-lane fairness, weather/customer stochasticity, policy overfitting, extrapolating one restaurant to all restaurants, data leakage, and AI eval conflation.

Finish with:

- `Decisions required before implementation` table: owner, options, recommended default, impact, blocker.
- `Definition of done` checklist with objectively testable criteria.
- `Open questions` with references to relevant files/sections.
- `Suggested first PR` containing the smallest independently testable implementation slice.

## 13. Writing and quality requirements

- Produce **one complete, well-structured `EVAL.md`** in the repository root (or the repo's established docs directory if clearly required). Make it detailed, concrete, and implementation-ready, not generic eval advice.
- Prioritize agreement with `ENGINE.md` and `CONTRACTS.md`; where they conflict, surface the conflict instead of silently rewriting either.
- Use tables, formulas with units, Mermaid diagrams, worked examples, schema examples, pseudocode, CLI proposals, and acceptance criteria.
- Every illustrative number must be labeled illustrative. Never invent measured savings, completed runs, passing tests, or data access.
- Keep the design practical for a hackathon: separate **must-build MVP** from optional sophistication, and explicitly say what can be deferred.
- Do not edit other repository files yet. At the end, summarize the proposed eval architecture, the 5 most consequential decisions, and the smallest next implementation task.
