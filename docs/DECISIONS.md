# Decisions

Final list after reconciling our independent design with the `Suyog` branch. Source: **B** = kept from the branch,
**O** = from our independent design, **M** = merged. Rows marked ⚠ change something the branch said; the team confirms them first.

| # | Decision | Why | Src |
|---|---|---|---|
| 1 | Restaurants paying demand charges | Large, credible savings | B |
| 2 | Owner sets importance (always_on / flexible / deferrable), limits, peak cap (kW), equipment counts, location, preferences | Owner in control | M |
| 3 | Every device reports to one hub; the hub interface is the swap point; real ESP32 via Convex (`HARDWARE=esp32`); bridge test `HARDWARE=sim_bridge` | Hardware is a drop-in, never on the critical path | M |
| 4 | Simulation runs in-process inside `engine/` (not a separate service) | Deterministic, fast, one less network hop; the hub interface still gives the swap | B (over O) |
| 5 | ⚠ Engine decides routine moves; when no in-rules move holds the cap it **escalates**; **Claude chooses** among engine-computed options within an owner-set **authority**; outside it the owner confirms; deadline → safe default | Claude as real supervisor for hard cases, numbers stay deterministic, owner keeps consent | M |
| 6 | Per-decision owner approvals removed; escalations replace them | One clear path for out-of-rules moves | O |
| 7 | All other AI changes are Proposals applied by code after owner confirmation (UI, ASI:One card, `confirm`) | Consent; Anthropic track guard | B |
| 8 | Fetch.ai is the primary track; Concierge uAgent wraps the Claude agent for ASI:One; whole owner workflow in ASI:One | Hackpack requirement | B |
| 9 | ⚠ Add Weather, Grid and Events agents feeding structured context; Claude sets `crowd_effect` as a category | Multi-agent + real-time data bonuses; better forecasts and escalation choices | O |
| 10 | Engine has no clock; runtime calls `step()`; escalation deadlines in sim time | Same engine for live, backtest, tests | B |
| 11 | Two lanes, same seeded customers; `compare_lanes()` in the engine | Fair visible comparison; browser computes nothing | B |
| 12 | SpacetimeDB = live shared kitchen; viewers write only request rows (`request_surge`); runtime identity writes state | Track asks for many concurrent writers; one writer for state | M |
| 13 | ⚠ SpacetimeDB module + Python live client owned by Kritazya | Balances Suyog's load; matches Kritazya's stated scope | O |
| 14 | Convex = durable records + devices + ESP32 bridge, plus `device_blocks`, `escalations`, `context_snapshots` | Every reading lands in a database whatever the hub | M |
| 15 | Nothing is the source of truth in two places (engine memory / SpacetimeDB / Convex) | Avoids drift | B |
| 16 | `/ws` fallback (`LIVE_TRANSPORT`), memory store fallback (`STORE`), `HARDWARE=off` | Demo survives outages | B |
| 17 | ⚠ Entire frontend (screens, data hooks, mocks, chat drawer) owned by Ashirwad | One owner per folder tree; lightens Suyog | O |
| 18 | Azure: Container Apps `backend` + `agents` (1 replica each) [Kritazya]; Static Web Apps [Ashirwad] | Stateful loop; always-on agents | M |
| 19 | Claude provider via env: Anthropic API default, Microsoft Foundry optional | Works today; Azure story if billing allows | O |
| 20 | Engine does no I/O | Pure, testable, identical everywhere | B |
| 21 | Owed-energy ledger repaid the same day; food-safety floor 50 % absolute | Exact conservation; safety | B |
| 22 | Replay 15-min steps, decider every step; January partial; escalations resolved by default in backtest | Data resolution; honest; reproducible | M |
| 23 | Strong timer baseline (best schedule from the previous month); all 12 months; worst case shown | Fair proof | B |
| 24 | Default limits per equipment type in the catalog | Defaults always pass the rules | B |
| 25 | Own branches (`kritazya`, `suyog`, `ashirwad`), merge to main only at gates | Independent work, controlled integration | O |
| 26 | Table pitch ~2 min + 3–5 min Fetch video (hacker guide). Devpost text says 3 min + 2 min Q&A: confirm at check-in | Format conflict between sources | B |
| 27 | Dataset id: **TBD (Kritazya)** ComStock full-service restaurant, county matching the tariff region | | B |
| 28 | Tariff (OpenEI URDB id): **TBD (Kritazya)** | | B |
| 29 | SpacetimeDB HTTP reducer call verified on the installed version: **TBD (Kritazya, Phase 1)** | | O |
| 30 | Events API: **TBD (Suyog)** | | O |

## What changed versus the `Suyog` branch
| Area | Branch | Final | Reason |
|---|---|---|---|
| Out-of-rules moves | Owner approves each decision; AI never decides | Escalation → Claude chooses within owner authority → owner beyond it → default at deadline | Kritazya's direction; keeps numbers in the engine and consent with the owner |
| Fetch | One chat agent | Concierge + Weather + Grid + Events | Primary track; multi-agent and real-time bonuses |
| Context | Fixed summer curve, no live data | Structured live context into the engine | Better forecasts; gives Claude something real to judge |
| SpacetimeDB owner | Suyog | Kritazya | Load balance; stated scope |
| Frontend data + chat | Suyog | Ashirwad | Load balance; one owner for `frontend/` |
| Hub swap | ESP32 via Convex | Same, plus formal hub interface, `sim_bridge` test and `device_blocks` | Make the ESP32 a provable drop-in; all data stored |
| Tasks | One TASKS.md + phase prompts | TIMELINE.md + one file per person in `docs/team/` | Independent development on own branches |
