# Design: API, runtime and Claude (owner: Suyog)

## Principles
- Thin API: validate → call the facade (queued between ticks) → return. No business logic.
- The run loop never blocks on Claude, agents, SpacetimeDB or Convex; each has a fallback.
- Claude only touches state through the two bounded tools; everything else is a Proposal.
- Typed everywhere: Pydantic from `backend/contracts`, OpenAPI drives frontend types.

The server between the UI and the engine, and the AI that talks to the owner. It moves time and messages;
it never decides and never computes numbers.

## Parts
| Part | Folder | What it does |
|---|---|---|
| FastAPI app | `api/` | REST endpoints + viewer `/ws` (CONTRACTS.md section 2) + hub socket `/ws/hub` (section 8) |
| Clock + run loop | `runtime/loop.py` | Owns simulated time: one `sim_tick` (1 sim min) per real tick, waits for `hub_report`, calls `step()` on both engine lanes |
| Hub link | `runtime/hub_link.py` | Accepts exactly one sim host (`hub_hello` → `hub_welcome`), sends `sim_build` / `sim_tick` / `sim_control`, receives `hub_report`; queues Commands for the next tick |
| Lanes | `runtime/lanes.py` | Holds two Kitchens (`without`, `with`) built from the same KitchenConfig + seed |
| Agent | `agent/` | Claude with tools (CONTRACTS.md section 4), explanations, chat |
| Store | `store/` | Convex writes (batched), in-memory fallback. `STORE=convex\|memory` |
| Live publisher | uses `backend/live/spacetime_client.py` (Kritazya) | One batched SpacetimeDB reducer call per real tick; reads new surge requests. `LIVE_TRANSPORT=spacetime\|ws` |
| Escalations | `runtime/escalations.py` | Sends open escalations to Claude, applies the returned id via the facade, creates owner Proposals when outside authority |
| Device bridge | `runtime/device_bridge.py` | `HARDWARE=esp32`: `with` lane commands → Convex; ESP32 readings → `ingest_reading()` |
| Proposals | `agent/proposals.py` | Creates, lists, confirms and applies Proposals (code path, never the model) |
| Fetch.ai agents | `agents/` | Concierge (Chat Protocol, wraps the Claude agent) + Weather, Grid, Events agents (design/AGENTS.md) |
| Fake engine | `fakes/fake_kitchen.py` | Same facade as the engine, canned results from `contracts/fixtures/facade/`. `KITCHEN_IMPL=fake\|real` |
| Fake sim host | `fakes/fake_hub_client.py` | Connects to `/ws/hub` and answers every `sim_tick` from `contracts/fixtures/hub_protocol/hub_to_server.jsonl`, so the loop runs with no browser. `HUB_IMPL=browser\|fake` |

## Kitchen lifecycle
1. `POST /api/kitchen` with KitchenConfig → build two engine Kitchens (`control="without"` and `"with"`), call
   `warm_up(...)` (source TBD, engine), send `sim_build` to the sim host, `reset_all` on SpacetimeDB, save the config to Convex `kitchens`.
2. `POST /api/sim/control {play, speed}` → start the clock. No sim host connected → stays paused with `sim_host_offline`.
3. Settings changes (importance, peak cap) are applied to **both** lanes' configs only where it matters:
   importance and cap affect only the `with` lane's decisions; the `without` lane ignores them.

## Run loop (asyncio task)
```
every real tick (0.5 s × 120 / speed; one tick = 1 sim minute):
    surges += live.consume_surges() + rest_surges.drain()   # judges' phone buttons (SpacetimeDB) + REST
    for lane in lanes: lane.set_context(context.latest())    # only when it changed (context is fetched periodically)
    report = await hub.tick(tick_id, sim_ts, 1, surges, context.physical_inputs(), pending_commands)
                                                  # sim_tick → hub_report; none within 2 s → pause "hub_waiting"
    for r in bridge.pending_readings():           # HARDWARE=esp32 only; real device = with lane
        lanes.with_.ingest_reading(r)
    states = {}
    for lane in (without, with):
        states[lane.control] = lane.step(1, report.reports[lane.control])   # engine replans every 5 sim min
        for d in states[lane.control].new_decisions: handle_decision(d)
        for e in states[lane.control].new_escalations: escalations.submit(e)   # async; never blocks
    pending_commands = states["without"].new_commands + states["with"].new_commands   # includes owner commands
    comparison = compare_lanes(states["without"], states["with"])
    bridge.forward(states["with"].new_commands)   # only commands for ESP32-mapped devices
    live.publish(states, comparison)              # SpacetimeDB (the UI's live source), or /ws when LIVE_TRANSPORT=ws
    store.buffer(states, report.acks)             # Convex, flushed once per real second
    tick_id += 1; sim_ts += 1 min
```
- Speeds: 1×, 30×, 120× (default), 600×. Pause / reset. Speed only changes the real interval; a tick is always 1 sim minute.
- Commands produced at tick *n* reach the appliances in tick *n + 1* (one sim minute later). Command acks go to Convex `commands`.
- Sim host disconnects → pause (`sim_host_offline`) + warning; on reconnect re-send `sim_build` and resume.
- **Escalation clock:** while an escalation is open, outside demo mode drop the send interval to `ESCALATION_SPEED`
  (default 1×; `slowed_reason = "escalation"`) and restore the owner's speed when it resolves or expires; the engine applies the
  default at the deadline. **Demo mode:** pause instead (`paused_reason = "escalation"`) and resume when it resolves.
  Rationale and the early-escalation rule: ARCHITECTURE.md → Time.
- Never call the AI inside the loop. Explanations are queued.

## Handling decisions
- `executed` → push `decision` message immediately with a **template** explanation; queue an AI explanation if
  `effect.saving_usd ≥ 1` (configurable). When the AI replies, push an updated `decision` message (`explanation_source: "ai"`).

## Escalations (`runtime/escalations.py`)
1. New escalation → publish it (SpacetimeDB `live_escalation`, Convex `escalations`, `/ws escalation`).
2. Ask Claude with: options (engine numbers), context summary, owner preferences, authority. Claude must call
   `choose_escalation_option(option_id, rationale)`; the id is an enum of the offered ids.
3. `kitchen.resolve_escalation(id, option_id, "claude", rationale)`. If the engine returns `awaiting_owner`, create a Proposal
   (`kind: resolve_escalation`) shown in the UI and ASI:One.
4. Claude timeout (8 real s) or error → do nothing; the engine applies the default at the deadline. Log it.
- Max **one** AI call in flight; if the queue is longer than 3, older items keep their template text.

## AI agent
**Role:** explain, answer, help the owner configure, and choose among engine options during escalations. Never compute; never apply a change except through the two bounded tools (CONTRACTS.md section 4).

System prompt essentials:
- You are WattWise's assistant for a restaurant owner. Be brief, plain, friendly.
- Only state numbers that appear in tool results. If you need a number, call a tool.
- You cannot control devices. To change importance, the cap, your authority, undo a decision or add a customer event,
  call a `propose_*` tool; it applies only after the owner confirms.
- In an escalation, choose the option that best fits the context and the owner's preferences; explain in one sentence
  using the option's numbers. Prefer options within your authority; choose `ask_owner` when the trade-off is the owner's to make.
- When explaining a decision, say what changed, why (reason_code + forecast), and the effect from the tool.

Tools: see CONTRACTS.md section 4. Implementation = thin wrappers over facade calls.
Template fallback (no API key / timeout > 3 s), e.g. `"Delayed {device} {value} min to avoid a new peak ({peak_before_kw} → {peak_after_kw} kW)."`
Chat replies stream over WebSocket (`chat_delta`, `chat_done`).

## Proposals and owner confirmation
- `propose_*` tools create a Proposal (CONTRACTS.md) in Convex `proposals` and push a `proposal` message.
- Confirm paths, all handled by code in `agent/proposals.py`: `POST /api/proposals/{id}/confirm` (UI), an ASI:One card
  button, or a `confirm` / `yes` reply to the latest pending Proposal (matched by code in `agents/concierge.py`, not by the model).
- Applying = the normal facade call (`set_importance`, `set_peak_cap`, `set_authority`, `undo`, `resolve_escalation`) or queueing
  a customer event in the runtime. Escalation proposals expire at the escalation deadline.

## Fetch.ai Concierge (summary; full design in AGENTS.md)
- uAgent (`uagents`) with the Agent Chat Protocol (`uagents_core.contrib.protocols.chat`), acknowledges every message,
  `publish_manifest=True`, mailbox mode so it works from Azure or a laptop, seed from `FETCH_AGENT_SEED`.
- Registered on Agentverse and categorized Innovation Lab; discoverable in ASI:One. README lists its name and address.
- Each chat message → the same Claude agent and tools as the dashboard chat → text reply (Interactive Cards if time).
- Must work inside ASI:One with no custom frontend: ask forecast/plan, hear escalation choices, undo, change a rule, see savings.
- A failed tool call returns a short plain message and the agent keeps the session alive. Never a stack trace.
- Bonus only after Gate 3: Payment Protocol (Stripe test mode) for a monthly plan.

## Store
Convex tables: CONTRACTS.md section 6 (incl. `escalations`, `device_blocks`, `context_snapshots`). The Python side uses the Convex Python client (`pip install convex`).
Live state is not stored here; it goes to SpacetimeDB (CONTRACTS.md section 5).
Batch writes once per real second. If Convex is unreachable, switch to the in-memory store (same interface) and emit
`warning: store_down`.

## FakeKitchen (build in Phase 1)
Implements every facade method on fixture data (`contracts/fixtures/facade/`). `step(1, hub_report)` returns contract-shaped
TickStates whose meter follows the given HubReport,
emits a fake Decision every ~10 sim minutes and a fake Escalation every ~30. Lets the API and AI be built and
demoed before the real engine exists.

## Errors
Engine `RuleError` → HTTP 422 with the message. Unknown device → 404. Never crash the run loop: log and continue.
SpacetimeDB unreachable → switch to `/ws`, emit `live_transport_down`. Convex unreachable → memory store, `store_down`.
No ESP32 reading for 30 s → that device back to simulated, `hub_offline`.

## Hosting
Runs on Azure Container Apps with **exactly one replica** (min = max = 1): lanes, run loop and open escalations live in
this process. `/api/health` is the probe. See `docs/design/AZURE.md`.
