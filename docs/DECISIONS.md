# Decisions (final)

| # | Decision | Why |
|---|---|---|
| 1 | Target user: restaurants paying demand charges | Large, credible savings; problem most people don't know |
| 2 | Three importance classes chosen by the owner: always_on, flexible, deferrable | Owner stays in control; engine knows exactly what it may touch |
| 3 | Owner sets a peak cap in kW and the equipment list + counts in the UI | Interactive, configurable kitchen |
| 4 | Every device reports to one hub. Simulated ESP32 by default; optional real ESP32 hub through Convex (`HARDWARE=esp32`) driving a few low-voltage stand-in loads | Realistic architecture; hardware is additive and never on the critical path (one env var switches back) |
| 5 | Engine decides and executes; AI explains, answers and proposes, never decides. A proposal is applied by code only after an owner confirmation (UI, ASI:One card, or a `confirm` reply) | Deterministic, fast, testable, honest numbers; still lets the owner run everything from ASI:One |
| 6 | Engine has no clock; run loop calls step() | Same engine for live (120×), backtest (max speed), tests, two lanes |
| 7 | Two lanes in the live demo (without / with WattWise), same seeded customers | Visible, fair comparison |
| 8 | Live history warm-up: simulate 21 days with no control at startup | Forecaster works from minute one, matches the configured kitchen |
| 9 | Proof on historical data with a real named tariff; all 12 months; strong timer baseline | Fair, no cherry-picking |
| 10 | Historical load split onto devices by a fixed recipe (engine code, not AI) | Same input → same output; sums exactly |
| 11 | Frontend types generated from OpenAPI + WS schema + SpacetimeDB bindings + Convex types | No drift between Python and TypeScript |
| 12 | Claude Code + CLAUDE.md + subagents (committed in `.claude/agents/`); Python engine | One consistent workflow, shared by the whole team |
| 13 | Dataset id: **TBD (Kritazya)**: ComStock full-service restaurant, county in the same region as the tariff. Record county + timestamp convention | Lunch rush must land at the right local hour for the tariff's time-of-use windows |
| 14 | Tariff (OpenEI URDB id): **TBD (Kritazya)**: real named commercial rate with demand charges | Real, checkable bill |
| 15 | Primary track: **Fetch.ai**. Also targeted: Convex, Microsoft (Built for the Real World + Customer Impact), Anthropic, SpacetimeDB, Cal Hacks general prizes. Dropped: Hyphenate, Tiger Data | Sponsor plan agreed Friday night |
| 16 | Live shared state in SpacetimeDB; FastAPI `/ws` kept as fallback (`LIVE_TRANSPORT`) | Every viewer and judge sees and plays in one kitchen; the demo survives a SpacetimeDB outage |
| 17 | Durable records and the ESP32 bridge in Convex; in-memory fallback (`STORE`). Tiger Data dropped | Reactive push to the ESP32 with no polling; one store instead of two |
| 18 | Each backend owns one job: SpacetimeDB = what ticks, Convex = records and devices, engine memory = the simulation | No data is the source of truth in two places |
| 19 | Owner chat through a Fetch.ai uAgent (Agent Chat Protocol, Agentverse, ASI:One) wrapping the same Claude agent as the dashboard chat | Fetch.ai requires the whole owner workflow inside ASI:One |
| 20 | Deploy on Azure Container Apps with exactly one replica + Azure Static Web Apps | Lanes and run loop live in memory; Microsoft judges production readiness |
| 21 | The engine does no I/O; network code lives in runtime/, store/, agent/ | Engine stays pure, testable and identical in live, replay and tests |
| 22 | `compare_lanes()` in the engine computes saved today and peak avoided | The browser and the API never compute numbers |
| 23 | Flexible devices keep an owed-energy ledger repaid the same day; physics models only shape timing | Exact energy conservation is testable |
| 24 | Replay steps 15 minutes and the decider runs every step (live: every 5 sim minutes) | Matches the data's resolution |
| 25 | January is scored from day 22 (warm-up first), its timer fitted on the warm-up weeks, and labeled partial | Honest "all 12 months" |
| 26 | Default limits live per equipment type in the catalog (`default_limits`) | Defaults never violate the refrigeration food-safety floor |
| 27 | Table pitch 2 min (live demo) + separate 3 to 5 min video for Fetch.ai | Cal Hacks judging format + Fetch.ai deliverable |
| 28 | Owners: Kritazya = engine brain, data + proof, Azure · Suyog = API + AI, Fetch.ai, SpacetimeDB, Convex, ESP32, frontend data + chat · Ashirwad = simulation, frontend screens | Agreed Friday night; frontend split by folder so two people never edit the same files |
