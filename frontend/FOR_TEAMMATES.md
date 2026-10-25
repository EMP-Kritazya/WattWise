# To-do for Kritazya and Suyog from Ashirwad's side

Updated Oct 24 for `main` at `0dc6a34` (browser simulation design). My work is on branch **`ashirwad`**; nothing is merged.
Full plan: `frontend/PLAN.md`. I build only against `contracts/fixtures/` and touch only `frontend/`,
`backend/data/equipment_catalog.json` and the `infra/` Static Web Apps files.

## Where my side stands (verified Oct 24)
- **Contract types and fixture data layer:** done. `VITE_MOCKS=1` serves REST, viewer `/ws`, SpacetimeDB rows and a mock `/ws/hub` server, all from `contracts/fixtures/`.
- **Browser simulation and hub:** done (`frontend/src/sim/`, `frontend/src/hub/`), along with the `/sim` sim host tab. On the full 120-tick `server_to_hub.jsonl` stream, my hub's `hub_report`s match `hub_to_server.jsonl` exactly in:
  - every ack (`command_id`, `ok`, `applied_value`, `reason`);
  - every `ts`;
  - every field name;
  - device order.

  Only the physical kW values differ, which ASHIRWAD.md allows. Two runs on the same seed give byte-identical output.
- **Catalog:** `equipment_catalog.json` matches the contract shape and the fixture catalog values exactly.
- **Still to do on my side:** the Live screen redesign (Charts | Simulation, right rail, energy + cost strip), Builder peak goal, Proof, the lint rules, Static Web Apps.

---

## Suyog: your to-do for when we integrate
1. **`/ws/hub` must behave like the `hub_protocol/` fixtures,** because my hub already does:
   - reply `hub_welcome` to my `hub_hello` (`{protocol: 1, hub_id: "sim_hub", role: "sim_host", client: "wattwise-web/0.1"}`); refuse a second host with `accepted: false, reason: "host_taken"`;
   - send `sim_build` (config, catalog, roster devices, seed, `start_sim_ts`);
   - send `sim_tick` *n + 1* only after my `hub_report` *n* arrives, with Commands for both lanes in `commands` (each with its `lane`);
   - send a surge once, in the tick it starts; I keep it active for `duration_min`;
   - `sim_control` for play, pause, reset and speed.
2. **Reconnect:** re-send `sim_build`, then replay past ticks with `replay: true`. Please agree the cue for "last replayed tick" with Kritazya (question Q3 below).
3. **REST and viewer `/ws` exactly as CONTRACTS.md §2:**
   - `GET /api/kitchen` returns `{config, devices, tariff}`;
   - errors are `{detail}` with 404 or 422;
   - "→ ok" means `{"ok": true}`;
   - `ClockState` includes `tick_id` and `slowed_reason`.
   My mocks serve the `rest/` and `ws/` fixtures, so matching them byte for byte means the UI just works.
4. **Surges:** with `LIVE_TRANSPORT=ws`, the +20 / +40 buttons call `POST /api/events/customers`.
5. **CORS:** allow the Static Web Apps origin (URL sent once it's deployed). Make `wss://…/ws/hub` and `/ws` reachable from the browser.
6. **First integration run, when the team says so:**
   - your API with `KITCHEN_IMPL=fake`;
   - my `/sim` tab pointed at your `/ws/hub`;
   - viewer tabs on `LIVE_TRANSPORT=ws`.

## Kritazya: your to-do
1. **Answer the contract questions below.** Until then I keep the code matching CONTRACTS.md as written.
2. **SpacetimeDB:**
   - send the generated TypeScript bindings (or the `spacetime generate` command);
   - send the hosted URI and DB name;
   - confirm the `request_surge(customers, duration_min)` signature.
   I'll swap them in behind `useLive()` with no screen changes.
3. **Types:** commit `contracts/ws_messages.schema.json` so `npm run gen:types` can replace my hand-written stub types.
4. **Container Apps:** send the backend URL and the `wss` URL; they become build-time env for Static Web Apps.
5. **Demo mode:** provide a cached backtest result for the Proof screen in `DEMO_MODE`.

## Contract questions (open)
- **Q1, Proof data:** `BacktestResult` has no savings columns, busiest-day series, sensitivity rows or **Replay month** series. UI.md asks for all four, and the browser may not compute them. What shape will carry them?
- **Q2, Context strip:** UI.md wants "next hours" and a price sparkline, but `live_context` holds only summary strings. Should the strip read `GET /api/context`, or will `live_context` gain hourly columns?
- **Q3, Reconnect replay:** the hub "answers only the last replayed tick", but it can't tell which replayed tick is last. What's the cue (for example, the first `replay: false` tick)?
- **Q4, Tariff list:** there's no tariff list endpoint. The Builder fixes `demo_tariff_v1` for now.
- **Q5, Owner on the graph:** `owner` isn't an AgentLog agent name. Should owner actions appear on the Agent Network graph?
- **Q6, Missing docs:** CLAUDE.md points to `docs/TIMELINE.md` and `docs/DECISIONS.md`, which were removed. Where do gates and merge order live?
- **Q7, Base branch:** `architecture-separation` doesn't exist on GitHub. Is `main` at `0dc6a34` the base? (I rebased `ashirwad` onto it.)
- **Q8, Owner-approved commands beyond limits:** an escalation option like `deep_reduce_hvac` (30 %, below `min_power_pct` 40) or `extend_delay_*` (past `max_delay_min`) must reach the appliance as asked. SIMULATION.md says appliances enforce only physics. Confirm the simulation should **not** clamp to the owner's limits, only to physical limits. Fixture example: GAPS.md's 20 % physical floor.

## Housekeeping
My old Python simulation only ever existed on `ashirwad` and has been deleted, so nothing lands in `backend/engine/` when we merge.
