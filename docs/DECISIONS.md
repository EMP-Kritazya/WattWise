# Decisions (final)

| # | Decision | Why |
|---|---|---|
| 1 | Target user: restaurants paying demand charges | Large, credible savings; problem most people don't know |
| 2 | Three importance classes chosen by the owner: always_on, flexible, deferrable | Owner stays in control; engine knows exactly what it may touch |
| 3 | Owner sets a peak cap in kW and the equipment list + counts in the UI | Interactive, configurable kitchen |
| 4 | Every device reports to one hub (simulated ESP32); physical ESP32 out of scope | Realistic architecture without hardware risk |
| 5 | Engine decides and executes; AI explains and talks, never decides | Deterministic, fast, testable, honest numbers |
| 6 | Engine has no clock; run loop calls step() | Same engine for live (120×), backtest (max speed), tests, two lanes |
| 7 | Two lanes in the live demo (without / with WattWise), same seeded customers | Visible, fair comparison |
| 8 | Live history warm-up: simulate 21 days with no control at startup | Forecaster works from minute one, matches the configured kitchen |
| 9 | Proof on historical data with a real named tariff; all 12 months; strong timer baseline | Fair, no cherry-picking |
| 10 | Historical load split onto devices by a fixed recipe (engine code, not AI) | Same input → same output; sums exactly |
| 11 | Frontend types generated from OpenAPI + WS schema | No drift between Python and TypeScript |
| 12 | Claude Code + CLAUDE.md + subagents; Python engine | One consistent workflow |
| 13 | Dataset id: ______ | |
| 14 | Tariff (OpenEI URDB id): ______ | |
| 15 | Primary sponsor track after day-one booth visit: ______ | |
