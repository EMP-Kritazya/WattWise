# Timeline, gates and merges

Pacific time. Coding starts **Sat 12:00 AM**. Devpost deadline **Sun 9:00 AM** (submit by 8:30). Judging 10:30–12:30, whole team at the table.
Detailed tasks: `docs/team/KRITAZYA.md`, `SUYOG.md`, `ASHIRWAD.md`. Tick tasks there.

| Phase | Time | Focus | Gate (all must be true) |
|---|---|---|---|
| 0 | Fri → Sat 12:00 AM | Docs merged, accounts, data downloaded, booth visits planned | Everyone pulled main; `architecture-reviewer` run on docs |
| 1 | Sat 12:00 → 2:00 AM | Skeleton + seams + fakes on own branches | **Merge 1:** UI renders fake live rows from SpacetimeDB and mock REST; API serves FakeKitchen; engine facade stubs import; `pytest` + `npm run build` + `spacetime build` pass; Azure skeleton health green |
| 2 | 2:00 → 9:00 AM | Simulation + meter + live publishing + context agents | **Merge 2:** `KITCHEN_IMPL=real`; build a kitchen → both lanes run → two browsers see the same kitchen → a judge's surge changes both → context strip shows live weather and price |
| 3 | 9:00 AM → 3:00 PM | Brain + escalations + Claude + ASI:One | **Merge 3:** hot evening + event + 40-customer surge → routine moves → an escalation → Claude chooses within authority → With lane holds the cap (or owner confirms); whole owner flow works in ASI:One; identical run with AI off |
| 4 | 3:00 → 9:00 PM | Proof + ESP32 + polish | **Merge 4 = feature freeze:** backtest checks pass (`backtest-auditor`); Proof screen; ESP32 via `sim_bridge` then real if healthy; Devpost draft |
| 5 | 9:00 PM → 4:00 AM | Deploy, harden, record | Azure release; `demo-readiness` GO; 5 clean `DEMO_MODE` runs; video; ASI:One submission agent registration |
| 6 | 4:00 AM → 12:30 PM | Pitch | Rehearsed 5+ times; Devpost final by 8:30 |

## Merge rules
- Merge order at each gate: **Kritazya** (contracts/engine/live) → **Suyog** (API/runtime/agents) → **Ashirwad** (frontend/simulation).
- Each PR: `architecture-reviewer` APPROVE, tests green, no edits in other people's folders.
- Contract changes between gates: PR to `main` touching only `docs/CONTRACTS.md` + `backend/contracts/` + bindings, run `contract-sync`, everyone rebases.
- Sleep in shifts: in Phases 2 and 5 at most one person sleeps at a time.

## Cut list (in order)
1. BDG2 real-meter check 2. Claude replay week 3. Extra tariffs in sensitivity 4. Events agent (keep Weather + Grid)
5. Thermal model (fixed HVAC curve) 6. Real ESP32 loads (keep `sim_bridge` + LED) 7. Interactive Cards 8. 600× speed
Never cut: Builder, two-lane live view, hub, decider + rules, escalations with Claude + defaults, Weather + Grid context,
ASI:One owner flow, SpacetimeDB shared kitchen, backtest with checks, demo mode + video.
