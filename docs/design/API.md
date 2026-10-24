# Design: API + AI (owner: API teammate)

The server between the UI and the engine, and the AI that talks to the owner. It moves time and messages;
it never decides and never computes numbers.

## Parts
| Part | Folder | What it does |
|---|---|---|
| FastAPI app | `api/` | REST endpoints + `/ws` WebSocket from CONTRACTS.md section 2 |
| Run loop | `runtime/loop.py` | Moves simulated time by calling `step()` on both lanes |
| Lanes | `runtime/lanes.py` | Holds two Kitchens (`without`, `with`) built from the same KitchenConfig + seed |
| Agent | `agent/` | Claude with tools (CONTRACTS.md section 4), explanations, chat |
| Store | `store/` | Tiger Data writes (batched), in-memory fallback |
| Fake engine | `fakes/fake_kitchen.py` | Same facade as the engine, canned results. `KITCHEN_IMPL=fake|real` |

## Kitchen lifecycle
1. `POST /api/kitchen` with KitchenConfig → build two Kitchens (`control="without"` and `"with"`), call
   `warm_up(21)` on both, create **one** `CustomerSource(seed)`.
2. `POST /api/sim/control {play, speed}` → start the run loop.
3. Settings changes (importance, peak cap) are applied to **both** lanes' configs only where it matters:
   importance and cap affect only the `with` lane's decisions; the `without` lane ignores them.

## Run loop (asyncio task)
```
every real tick (≈ 0.5 s at speed 120 → 1 sim minute):
    events = customer_source.events(sim_ts, 1, surges)
    for lane in (without, with):
        state = lane.step(1, events)
        broadcast {"type": "tick", "data": state}
        for d in state.new_decisions: handle_decision(d)
    store.buffer(states)        # flushed once per real second
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
**Role:** explain, answer, help the owner configure. Never decide, never compute.

System prompt essentials:
- You are WattWise's assistant for a restaurant owner. Be brief, plain, friendly.
- Only state numbers that appear in tool results. If you need a number, call a tool.
- You cannot control devices. To change importance or the peak cap, call a `propose_*` tool; the owner confirms in the UI.
- When explaining a decision, say what changed, why (reason_code + forecast), and the effect from the tool.

Tools: see CONTRACTS.md section 4. Implementation = thin wrappers over facade calls.
Template fallback (no API key / timeout > 3 s), e.g. `"Delayed {device} {value} min to avoid a new peak ({peak_before_kw} → {peak_after_kw} kW)."`
Chat replies stream over WebSocket (`chat_delta`, `chat_done`).

## Store
Tables (time-series): `ticks(lane, ts, total_kw, block_avg_kw, month_peak_kw, cost_usd_today)`,
`device_readings(lane, ts, device_id, power_kw, state)`, `decisions`, `commands`, `backtest_results`.
Batch writes once per real second. If the database is unreachable, use the in-memory store (same interface).

## FakeKitchen (build in hour 0–2)
Implements every facade method. `step()` returns TickStates with plausible numbers (sine-wave load + noise, seeded),
emits a fake Decision every ~10 sim minutes and an approval request every ~30. Lets the API and AI be built and
demoed before the real engine exists.

## Errors
Engine `RuleError` → HTTP 422 with the message. Unknown device → 404. Never crash the run loop: log and continue.
