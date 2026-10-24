# Design: API + AI (owner: Suyog)

The server between the UI and the engine, and the AI that talks to the owner. It moves time and messages;
it never decides and never computes numbers.

## Parts
| Part | Folder | What it does |
|---|---|---|
| FastAPI app | `api/` | REST endpoints + `/ws` WebSocket from CONTRACTS.md section 2 |
| Run loop | `runtime/loop.py` | Moves simulated time by calling `step()` on both lanes |
| Lanes | `runtime/lanes.py` | Holds two Kitchens (`without`, `with`) built from the same KitchenConfig + seed |
| Agent | `agent/` | Claude with tools (CONTRACTS.md section 4), explanations, chat |
| Store | `store/` | Convex writes (batched), in-memory fallback. `STORE=convex\|memory` |
| Live publisher | `runtime/spacetime_publisher.py` | One batched SpacetimeDB reducer call per real tick; reads new surge requests. `LIVE_TRANSPORT=spacetime\|ws` |
| Device bridge | `runtime/device_bridge.py` | `HARDWARE=esp32`: `with` lane commands → Convex; ESP32 readings → `ingest_reading()` |
| Proposals | `agent/proposals.py` | Creates, lists, confirms and applies Proposals (code path, never the model) |
| Fetch.ai agent | `agent/fetch_agent.py` | uAgent with the Agent Chat Protocol, registered on Agentverse, wraps the Claude agent |
| Fake engine | `fakes/fake_kitchen.py` | Same facade as the engine, canned results. `KITCHEN_IMPL=fake\|real` |

## Kitchen lifecycle
1. `POST /api/kitchen` with KitchenConfig → build two Kitchens (`control="without"` and `"with"`), call
   `warm_up(21)` on both, create **one** `CustomerSource(seed)`, save the config to Convex `kitchens`.
2. `POST /api/sim/control {play, speed}` → start the run loop.
3. Settings changes (importance, peak cap) are applied to **both** lanes' configs only where it matters:
   importance and cap affect only the `with` lane's decisions; the `without` lane ignores them.

## Run loop (asyncio task)
```
every real tick (≈ 0.5 s at speed 120 → 1 sim minute):
    surges += live.consume_surges()               # judges' phone buttons (SpacetimeDB) + REST surges
    events = customer_source.events(sim_ts, 1, surges)
    for r in bridge.pending_readings():           # HARDWARE=esp32 only; real device = with lane
        lanes.with_.ingest_reading(r)
    states = {}
    for lane in (without, with):
        states[lane.control] = lane.step(1, events)
        for d in states[lane.control].new_decisions: handle_decision(d)
    comparison = compare_lanes(states["without"], states["with"])
    bridge.forward(states["with"].new_commands)   # only commands for ESP32-mapped devices
    live.publish(states, comparison)              # SpacetimeDB, or /ws when LIVE_TRANSPORT=ws
    store.buffer(states)                          # Convex, flushed once per real second
```
- Speeds: 1×, 30×, 120× (default), 600×. Pause / reset.
- **Demo mode:** when an approval is pending, pause the loop (`clock.paused_reason = "awaiting_approval"`),
  resume on approve/decline. Outside demo mode, pending approvals expire (engine handles expiry).
- Never call the AI inside the loop. Explanations are queued.

## Handling decisions
- `executed` → push `decision` message immediately with a **template** explanation; queue an AI explanation if
  `effect.saving_usd ≥ 1` (configurable). When the AI replies, push an updated `decision` message (`explanation_source: "ai"`).
- `awaiting_approval` → push `approval_request` (template text first, AI text when ready).
- Max **one** AI call in flight; if the queue is longer than 3, older items keep their template text.

## AI agent
**Role:** explain, answer, help the owner configure. Never decide, never compute, never apply a change itself.

System prompt essentials:
- You are WattWise's assistant for a restaurant owner. Be brief, plain, friendly.
- Only state numbers that appear in tool results. If you need a number, call a tool.
- You cannot control devices. To change importance or the peak cap, approve/undo a decision, or add a customer event,
  call a `propose_*` tool. The change happens only when the owner confirms (UI Confirm, ASI:One card, or `confirm`).
- When explaining a decision, say what changed, why (reason_code + forecast), and the effect from the tool.

Tools: see CONTRACTS.md section 4. Implementation = thin wrappers over facade calls.
Template fallback (no API key / timeout > 3 s), e.g. `"Delayed {device} {value} min to avoid a new peak ({peak_before_kw} → {peak_after_kw} kW)."`
Chat replies stream over WebSocket (`chat_delta`, `chat_done`).

## Proposals and owner confirmation
- `propose_*` tools create a Proposal (CONTRACTS.md) in Convex `proposals` and push a `proposal` message.
- Confirm paths, all handled by code in `agent/proposals.py`: `POST /api/proposals/{id}/confirm` (UI), an ASI:One card
  button, or a `confirm` / `yes` reply to the latest pending Proposal (matched by code in `fetch_agent.py`, not by the model).
- Applying = the normal facade call (`set_importance`, `set_peak_cap`, `approve`, `undo`) or queueing a customer event in
  the runtime. Proposals expire with the decision they refer to.

## Fetch.ai agent (`agent/fetch_agent.py`)
- uAgent (`uagents`) with the Agent Chat Protocol (`uagents_core.contrib.protocols.chat`), acknowledges every message,
  `publish_manifest=True`, mailbox mode so it works from Azure or a laptop, seed from `FETCH_AGENT_SEED`.
- Registered on Agentverse and categorized Innovation Lab; discoverable in ASI:One. README lists its name and address.
- Each chat message → the same Claude agent and tools as the dashboard chat → text reply (Interactive Cards if time).
- Must work inside ASI:One with no custom frontend: ask forecast/plan, approve/undo, change a rule, see savings.
- A failed tool call returns a short plain message and the agent keeps the session alive. Never a stack trace.
- Bonus only after Gate 3: Payment Protocol (Stripe test mode) for a monthly plan.

## Store
Convex tables: CONTRACTS.md section 6 (`kitchens`, `decisions`, `commands`, `readings`, `device_map`, `hubs`, `proposals`,
`bills`, `backtest_results`). The Python side uses the Convex Python client (`pip install convex`).
Live state is not stored here; it goes to SpacetimeDB (CONTRACTS.md section 5).
Batch writes once per real second. If Convex is unreachable, switch to the in-memory store (same interface) and emit
`warning: store_down`.

## FakeKitchen (build in Phase 1)
Implements every facade method. `step()` returns TickStates with plausible numbers (sine-wave load + noise, seeded),
emits a fake Decision every ~10 sim minutes and an approval request every ~30. Lets the API and AI be built and
demoed before the real engine exists.

## Errors
Engine `RuleError` → HTTP 422 with the message. Unknown device → 404. Never crash the run loop: log and continue.
SpacetimeDB unreachable → switch to `/ws`, emit `live_transport_down`. Convex unreachable → memory store, `store_down`.
No ESP32 reading for 30 s → that device back to simulated, `hub_offline`.

## Hosting
Runs on Azure Container Apps with **exactly one replica** (min = max = 1): lanes, run loop and pending approvals live in
this process. `/api/health` is the probe. See `docs/design/INTEGRATIONS.md`.
