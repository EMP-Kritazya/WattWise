# WattWise · Claude Code master prompt (all phases)

How to use this file:
1. **Once, at the start (one person):** paste **Part A + Phase 0** into Claude Code from the repo root. Phase 0 brings the docs in line with the sponsor plan. Nobody writes code until it is merged.
2. **Every later session (everyone):** paste **Part A**, set `ROLE` and `PHASE`, then paste only that phase's block.
3. When a phase gate passes, tick it in `docs/TASKS.md` and move to the next phase.

Clock targets are Pacific time. Hard deadline: **Devpost by 9:00 AM Sunday** (we aim for 8:30). Judging runs 10:30 AM to 12:30 PM, needs the **whole team at the table** and a **live demo**.

---

## Part A · Session starter (paste every session)

```
You are working on WattWise for Cal Hacks 13.0.

ROLE  = <kritazya | suyog | ashirwad>
#  kritazya = engine brain, contracts, data + proof, Azure (infra/)
#  suyog    = api/, runtime/, agent/ (Claude + Fetch.ai), store/, fakes/, spacetime/, convex/, firmware/,
#             frontend src/data, src/mocks, src/types, src/features/chat
#  ashirwad = engine/devices.py, hub.py, customers.py, data/equipment_catalog.json,
#             frontend src/features/builder, live, feed, proof, src/components
#  Stay inside your folders. Need a change in someone else's folder? Say so and stop.
PHASE = <0 | 1 | 2 | 3 | 4 | 5 | 6>

Before anything else:
1. Read CLAUDE.md, then docs/ARCHITECTURE.md, then every doc CLAUDE.md lists for my role
   (CONTRACTS.md before touching any shared shape). Also read docs/DECISIONS.md and docs/TASKS.md.
2. Restate in 5 lines or fewer: my task for this phase, the files you will touch, and the gate we are aiming at.
3. If the change is over ~50 lines, give a plan and wait for my approval.

Standing rules (CLAUDE.md wins if anything here disagrees, and then you stop and ask):
- The engine decides and executes. Claude explains, answers and proposes. The engine must run with the AI off.
- No LLM ever computes a user facing number. Every kW, kWh and $ comes from an engine call or a tool result.
- always_on is never touched. flexible never goes below its minimum. deferrable always finishes by its deadline.
- Energy is moved, never deleted. Replay never reads a row at or after "now".
- Units in names (_kw, _kwh, _usd, _min, _pct). UTC inside, local time only at the edges. Seeds for anything random.
- Simulated data is labeled "simulated"; only real ESP32 readings may be labeled "measured".
- The engine imports nothing from api/, runtime/, agent/, store/, and does no I/O (no HTTP, no Convex, no SpacetimeDB).
  Anything that talks to the network lives in runtime/, store/, agent/ or hardware/.
- Unclear contract: stop and ask. Never invent a shape. Shape change = CONTRACTS.md in the same commit.
- Stubs are marked "# STUB:" and listed in your summary. Never silently fake data.
- Never commit secrets or datasets. Secrets live in .env (local) or Azure Container Apps secrets (cloud).
- Small diffs, one module per session. Run pytest and/or npm run build before saying done.

Sponsor stack (official once Phase 0 is merged):
- Fetch.ai: the owner workflow runs inside ASI:One through a uAgent with the Agent Chat Protocol,
  registered on Agentverse. Its brain is our Claude agent.
- Claude: explanations, Q&A, turning owner requests into proposals. Model from ANTHROPIC_MODEL.
- SpacetimeDB: the shared live kitchen every viewer sees (ticks, device states, feed, clock, surge requests).
- Convex: durable records (kitchens, decisions, commands, readings, proposals, bills, backtest results)
  and the bridge to the physical ESP32 through the convex-esp32 client.
- Microsoft Azure: Container Apps (API + run loop + uAgent, exactly ONE replica) and Static Web Apps (frontend).

End every session with: what changed, tests run and their result, stubs left, contract changes (if any),
the TASKS.md line you ticked, and which subagent should run next.
```

---

## Phase 0 · Reconcile the docs (Fri 11:00 PM → Sat 12:00 AM) · one person, docs only

> **Status (Fri Oct 23, 11 PM): applied.** Items 1 to 19 and 21 are done in the docs, plus the new
> `docs/design/INTEGRATIONS.md`. Still open: item 20 (dataset + tariff ids in DECISIONS.md #13, #14, Kritazya).
> Run this block only to re-check consistency or finish that.

```
PHASE 0. No application code in this phase. Goal: the docs describe the system we are actually building.

Step 1. Read every file in the repo. Produce a table "Conflict | Where | Proposed fix" covering at least the
items below, plus anything else you find. Then STOP and wait for my approval on each row.

Step 2. After approval, apply the edits, run a final consistency pass (every term, path, env var and endpoint
named the same way in every file), and commit on a branch: "docs: align with sponsor stack".

Known conflicts to resolve:

Stack
 1. Tiger Data is the store in CLAUDE.md (Stack, repo layout), docs/design/API.md (Store), README (.env) and TASKS.
    Replace with: Convex for durable records, SpacetimeDB for live shared state, in-memory fallback kept.
    store/ keeps one interface with three backends: memory | convex (+ spacetime publisher in runtime/).
 2. "Physical ESP32 out of scope" in ARCHITECTURE.md, DECISIONS.md #4 and SIMULATION.md.
    New wording: simulated hub is the default; an optional physical ESP32 hub (HARDWARE=esp32) talks to
    Convex. The engine still never does I/O; a runtime/device_bridge.py moves commands out and readings in.
 3. Seam 1 is only REST + /ws. Add SpacetimeDB as the live transport (LIVE_TRANSPORT=spacetime|ws, ws kept
    as fallback). Add a "SpacetimeDB tables" and a "Convex tables" section to CONTRACTS.md.
    Update CLAUDE.md "types are generated" rule: OpenAPI + ws schema + SpacetimeDB generated bindings
    + Convex generated types are all allowed generated sources; nothing hand written.
 4. AI wording. CLAUDE.md, ARCHITECTURE.md and API.md say the AI never acts and Confirm lives in the React
    chat drawer. Fetch.ai requires the whole owner workflow inside ASI:One. New rule: the engine still decides;
    the agent may call approve()/apply a proposal ONLY after an explicit owner confirmation (a tap on an
    ASI:One card or the UI Confirm button). Record this as a new DECISIONS.md row.
 5. Azure is not mentioned anywhere. Add a Deploy section to README + ARCHITECTURE: Container Apps with
    min replicas = max replicas = 1 (lanes and run loop are in memory; scale to zero or scale out breaks them),
    Static Web Apps for the frontend, secrets in Container Apps.

Repo hygiene
 6. .gitignore ignores .claude/ but CLAUDE.md and TASKS rely on shared .claude/agents/, which do not exist yet.
    Remove .claude/ from .gitignore (ignore only .claude/settings.local.json), create the 5 subagents
    (architecture-reviewer, contract-sync, engine-math-verifier, backtest-auditor, demo-readiness) as short
    .md files whose instructions come straight from CLAUDE.md, CONTRACTS.md, ENGINE.md section 7 and
    DATA_AND_PROOF.md "Checks". Add to .gitignore: data/, .venv/, node_modules/, __pycache__/, dist/, .DS_Store,
    .env.*, and git rm --cached the committed .DS_Store files.

Contract gaps
 7. API must catch RuleError but may only import Kitchen, CustomerSource, run_backtest. Export RuleError too.
 8. "Saved today" is computed in the browser (UI.md) but ARCHITECTURE says the frontend never calculates and
    golden rule 2 says every $ comes from the engine. Add engine function compare_lanes(without, with_) ->
    LaneComparison { saved_today_usd, peak_avoided_kw } exported from engine; runtime attaches it to each tick.
 9. AI tool add_customer_event acts without confirmation and calls REST instead of the facade; get_bill reads the
    store. Make add_customer_event a proposal (owner confirms) routed through runtime; get_bill reads a Bill
    returned by an engine call or a stored engine result only.
10. ImportanceLimits default flexible min_power_pct = 40, but rules.py enforces a 50% food safety floor for
    refrigeration and walk_in_cooler defaults to flexible. Move default limits per type into
    equipment_catalog.json (default_limits) so defaults never raise RuleError.
11. TickState has no commands, so a real device can never receive one. Add new_commands: list[Command].
12. Add facade call ingest_reading(device_id, power_kw, ts) for ESP32 readings; Device/HubReport source becomes
    "simulated" | "measured". Engine stays I/O free.
13. forecast_kw example shows 4 values; spec says next 2 h in 15 min steps = 8. Fix the example.

Engine and proof wording
14. Energy conservation "±1e-6 across lanes" cannot hold if HVAC/walk-in use a physics (thermal/cycling) catch-up.
    Define conservation with an explicit owed-energy ledger per flexible device that the decider must repay
    the same day; physics models only shape timing. (Thermal model is already cut item 3.)
15. "All 12 months": first 3 weeks are warm-up and the timer is fitted on the previous month, so January has
    neither. Write the honest version: January scored from day 22, its timer fitted on the warm-up weeks,
    and say so on the Proof screen.
16. Replay feeds 15 min rows but the decider runs every 5 sim min. State: in replay the step is 15 min and
    the decider runs every step.
17. ComStock timestamps are converted from EST and displayed in America/Los_Angeles against a PG&E tariff.
    Pick a ComStock profile in the same region as the tariff and verify the dataset's timestamp convention,
    or the lunch rush lands at the wrong local hour. Record dataset id + county in DECISIONS.md #13.

Schedule and people
18. TASKS says "submit by 8:30 AM; table by 8:00 AM". Hacker guide: Devpost deadline 9:00 AM, tables assigned
    after that, be at the table by 10:30, whole team present, live demo required, ~2 minute pitch suggested,
    Devpost draft by Saturday night. DEMO.md says a 3 min pitch; Fetch.ai also needs a 3 to 5 min video.
    Make DEMO.md a 2 min table pitch + separate 3 to 5 min recorded video script.
19. Owners (done): Kritazya = engine brain, data + proof, Azure; Suyog = API + AI, Fetch.ai, SpacetimeDB, Convex,
    ESP32, frontend data + chat; Ashirwad = simulation, frontend screens.
20. DECISIONS.md #13 to #15 are blank. Ask me for the dataset id and tariff id. #15 primary track = Fetch.ai,
    with Convex, Microsoft, Anthropic and SpacetimeDB as targeted tracks (Hyphenate and Tiger Data dropped).
21. Rebase TASKS.md phases onto the clock targets in this file (we start coding about Sat 12:00 AM).

Also add to README .env list: CONVEX_URL, SPACETIMEDB_URL, SPACETIMEDB_DB, SPACETIMEDB_TOKEN, LIVE_TRANSPORT,
HARDWARE, FETCH_AGENT_SEED, AGENTVERSE_API_KEY (if needed), STORE=memory|convex. Keep KITCHEN_IMPL and DEMO_MODE.

Gate 0: every row above is either fixed or explicitly marked "kept, because ...". Run architecture-reviewer
on the docs. Merge to main and tell the team to pull before writing code.
```

---

## Phase 1 · Skeleton + seams (Sat 12:00 AM → 2:00 AM)

```
PHASE 1. Everyone works in their own folders against fakes. Goal: every seam exists and carries
contract shaped data end to end, with nothing real behind it yet.

kritazya:
- backend/contracts/: Pydantic v2 models for every shape in CONTRACTS.md (including Reading, LaneComparison, Proposal).
- contracts/ws_messages.schema.json generated from the models (script, not by hand).
- backend/engine/__init__.py exporting exactly Kitchen, CustomerSource, run_backtest, compare_lanes, RuleError.
- engine/kitchen.py facade with every method raising NotImplementedError("# STUB: phase 2/3").
- Azure: resource group, Container Apps environment, Static Web App. Nothing deployed yet.
- tests: models round trip to JSON.

ashirwad:
- backend/data/equipment_catalog.json with default_limits per type and a source_note (placeholder values marked).
- engine/devices.py, hub.py, customers.py: classes and method signatures from SIMULATION.md, bodies "# STUB:".
- tests/simulation: catalog validates against EquipmentType; every default_limits passes the rules (ask Kritazya
  for the rules function signature; stub it until then).
- frontend: screen shells for Builder, Live, Proof that render from Suyog's mock hooks only.

suyog:
- FastAPI app with every REST endpoint, /ws and /api/health, backed by fakes/fake_kitchen.py
  (seeded sine load + noise, a fake Decision every ~10 sim min, an approval every ~30).
- runtime/loop.py skeleton (play/pause/reset, speeds 1/30/120), two lanes, ONE CustomerSource. store/ interface + memory.
- frontend scaffold: Vite + React + TS + Tailwind + shadcn/ui + Recharts, generated types (npm script),
  src/mocks streaming every ws message type, src/data hooks the screens use.
- convex/schema.ts + function stubs; spacetime/ module with tables + reducers (local); generated bindings.

Gate 1: merged to main; UI renders mock ticks; API serves FakeKitchen; pytest and npm run build pass;
SpacetimeDB and Convex dev deployments answer a hello call. Run architecture-reviewer.
```

---

## Phase 2 · Simulation (Sat 2:00 AM → 9:00 AM, sleep in shifts)

```
PHASE 2. Goal: a real simulated kitchen runs in both lanes and every browser sees it live through SpacetimeDB.

ashirwad (docs/design/SIMULATION.md):
- devices.py power models: fixed, cycling, demand_driven, job (thermal only if time, else a fixed HVAC curve).
- Devices obey hub commands: on, off, start, delay (minutes), reduce (power %), restore; deferrable jobs queue
  as "waiting"; flexible never below min_power_pct.
- customers.py: CustomerSource(seed, profile).events(ts, minutes, surges), seeded Poisson + surges.
- hub.py: collects HubReport each step, delivers Commands, logs every command.
- tests: same config + seed => identical day; a reduce never goes below the minimum; a job runs exactly cycle_min.
- frontend: Kitchen Builder complete; Live floor + Hub tile; two-lane chart with cap and month peak lines;
  KPI row using LaneComparison (no browser math); clock + surge buttons.

kritazya (docs/design/ENGINE.md section 1):
- meter.py; kitchen.step(), warm_up(21), snapshot(), owner_command(), ingest_reading(), compare_lanes(),
  wiring Ashirwad's devices + hub into the facade.
- tests: meter 40 kW x 60 min = 40 kWh, four 40 kW blocks, peak 40; owner_command protects a device 30 sim min;
  compare_lanes hand case from ENGINE.md section 7.

suyog:
- Real run loop with KITCHEN_IMPL=real, two lanes, shared CustomerSource, compare_lanes on every tick.
- runtime/spacetime_publisher.py: ONE batched publish_ticks call per real tick through
  POST /v1/database/<db>/call/<reducer> (no Python SDK); read surge_request rows each tick; fall back to /ws.
- store: Convex backend (pip convex), batched once per real second.
- frontend src/data: one live hook that switches between SpacetimeDB and /ws (LIVE_TRANSPORT).
- ESP32 bench test with convex-esp32 (S3 + PSRAM preferred, core >= 3.2, ArduinoJson 7):
  subscribe to commands:forDevice, toggle an LED, call commands:ack. No soldering at the venue.

Gate 2: build a kitchen in the UI -> both lanes run -> two browsers see the same kitchen -> clicking a device
changes both views. Run engine-math-verifier (covers simulation files too), then contract-sync if a shape moved.
Cut if late: thermal model, 30x speed, surge via SpacetimeDB (use REST surge instead).
```

---

## Phase 3 · Brain + AI + Fetch.ai agent (Sat 9:00 AM → 3:00 PM)

```
PHASE 3. Goal: the with lane stays under the cap on a surge, every decision is explained, and the owner can
run the whole workflow from ASI:One.

kritazya (ENGINE.md sections 2 to 7):
- forecaster (same weekday/time over 3 weeks, live ratio clamped 0.5 to 2.0), target, decider (delay first,
  then reduce, never always_on, owed-energy ledger), executor, rules (food safety floor), approve, undo,
  what_if, expiry, new_commands on TickState.
- Tests from ENGINE.md section 7 exactly: deferrable case (peak 46 -> 40, 3 kWh both ways), flexible case
  (HVAC 10 -> 6 kW, 1 kWh owed and repaid), daily energy equal across lanes, owed_kwh 0 at close,
  no Command ever targets always_on over a full day, no peeking guard raises on ts >= now.

suyog:
- Decision handling: template text immediately, AI text queued (one call in flight, 3 s timeout, labeled
  fallback), approval relay, demo mode pause while an approval is pending.
- agent/proposals.py + POST /api/proposals/{id}/confirm. Claude agent with the CONTRACTS.md tools; it quotes
  tool numbers only; it has no tool that changes state.
- agent/fetch_agent.py: uAgent (uagents) with the Agent Chat Protocol, mailbox mode, registered on Agentverse,
  Innovation Lab, publish_manifest=True, forwarding chat to the Claude agent. Must work in ASI:One with no
  custom frontend:
    "What will lunch cost me?" -> forecast + plan
    "Approve it" / "Undo the last one" -> proposal -> owner says confirm -> approve() / undo()
    "Never touch the walk-in after 9 PM" -> proposal -> confirm -> set_importance()
    "How much did we save this month?" -> engine numbers only
  Confirmation is matched by code, never by the model. Failed tool call -> short plain message.
- README: agent name + address, innovationlab and hackathon badges, how to run it.
- runtime/device_bridge.py (HARDWARE=esp32): with lane new_commands -> Convex; readings -> ingest_reading();
  firmware fail safe: no Convex contact for 30 s -> loads back to normal.
- frontend src/features/chat: chat drawer + proposal cards (same Proposals ASI:One uses).

ashirwad:
- frontend: decision feed with Undo and AI tag, approval modal, warning banners, tiles showing
  reduced / waiting / running_job states.
- simulation fixes Kritazya's decider needs (job queue timing, catch-up power above normal for flexible devices).

Gate 3: a +40 customer surge keeps the with lane under the cap; every decision has an explanation;
an owner can ask, approve and undo from ASI:One; the engine runs identically with ANTHROPIC_API_KEY unset.
Run engine-math-verifier and architecture-reviewer.
Cut if late: Interactive Cards, what_if tool, chat drawer (ASI:One is the required door).
```

---

## Phase 4 · Proof + sponsor depth (Sat 3:00 PM → 9:00 PM) · feature freeze at the gate

```
PHASE 4. Goal: honest 12 month savings on real data, stored in Convex, plus the physical ESP32 on stage.

kritazya (docs/design/DATA_AND_PROOF.md):
- Loader (electricity columns only, region + timestamp convention verified, kwh x 4 = kW), fixed distribution
  recipe (assumptions.yaml: base, low_flex, heavy_equipment, bad_forecast), replay at 15 min steps with the
  decider every step, run_backtest for without / timer (previous month; January on warm-up weeks) / with.
- Checks: without bill = raw bill to the cent, daily energy equal, 0 rule violations, zero flexibility => 0
  savings, no peeking guard never triggered. Sensitivity runs. Cache results. Run backtest-auditor.

suyog:
- Backtest endpoints + progress; results saved to Convex; cached results served in DEMO_MODE.
- ESP32 + INA219 + MOSFET modules switching two small 5 to 12 V loads mapped in Convex device_map with a scale;
  readings shown as "measured (scaled)". Breakouts with headers, breadboard, no soldering.
- Optional Fetch.ai bonus only if Gate 3 is solid: Payment Protocol (Stripe test mode).

ashirwad:
- Proof screen: exact data labels, 12 month table (January "partial"), busiest day chart, sensitivity table with
  the worst case highlighted, Replay month animation. Hardware badges + "measured (scaled)" on tiles.

Everyone: Devpost draft submitted tonight.
Gate 4 (feature freeze): Proof numbers pass every check; backtest-auditor returns CLEARED.
Cut list in order: BDG2 real meter check, extra tariffs, Payment Protocol, Interactive Cards, ESP32 loads
(keep LED demo), 600x speed. Never cut: Builder, two lane live view, hub, decider + rules, explanations,
backtest with checks, ASI:One workflow, demo mode + video.
```

---

## Phase 5 · Deploy, harden, record (Sat 9:00 PM → Sun 4:00 AM)

```
PHASE 5. Goal: it runs on Azure, survives bad WiFi, and the video is recorded.

kritazya:
- Azure Container Apps: one image for API + run loop + uAgent, min = max replicas = 1, secrets, /api/health probe,
  Application Insights if time. Frontend on Azure Static Web Apps. Env wired to hosted SpacetimeDB + Convex.

suyog:
- Hosted SpacetimeDB + Convex deployments; verify ASI:One reaches the cloud agent.
- Offline fallback on a phone hotspot: LIVE_TRANSPORT=ws + STORE=memory + HARDWARE=off.
- Register the project with the Cal Hacks ASI:One Submission Agent.

ashirwad:
- DEMO_MODE=1: fixed seed, preset Demo Café, Friday 11:30, 120x, cached backtest, AI text if < 3 s.
- Lead 5 clean runs in a row from cold start. Record and edit the 3 to 5 min video (DEMO.md, ASI:One flow first).

Everyone: run demo-readiness; Devpost: what each sponsor tool does, simulated vs measured, repo, agent address, video.
Gate 5: deployed URL works on a phone; video uploaded; Devpost complete except final polish.
```

---

## Phase 6 · Pitch and submit (Sun 4:00 AM → 12:30 PM)

```
PHASE 6. No code except a fix for a demo breaking bug, approved by the whole team.
- Sleep in shifts. Rehearse DEMO.md 5+ times; one person runs ASI:One, one runs the Live tab, one pitches.
- Devpost final by 8:30 AM (deadline 9:00). Check the README badges, agent address, public repo.
- Find the table number after 9:00, be there by 10:30, whole team stays until 12:30. Live demo required.
- Talk to the Fetch.ai, Convex, Microsoft, Anthropic and SpacetimeDB tables during or after judging.
```

---

## Subagent cadence (from CLAUDE.md)
| When | Run |
|---|---|
| Every gate, before merging to main | architecture-reviewer |
| Any shape change | contract-sync |
| After any engine change | engine-math-verifier |
| Before any savings number is shown | backtest-auditor |
| From Phase 5 and before rehearsals | demo-readiness |
