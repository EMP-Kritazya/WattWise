# Ashirwad — Simulation and the entire frontend

**Branch:** `ashirwad` · **Merge order:** third at every gate · **Mission:** the kitchen behaves like a real one, and everyone can see it.

## You own
`backend/engine/devices.py`, `hub.py`, `customers.py`, `fake_hub.py` · `backend/data/equipment_catalog.json` ·
`backend/tests/simulation/` · all of `frontend/` · `infra/` Static Web Apps. **Don't edit:** other engine files, api/, runtime/,
agent/, agents/, store/, live/, spacetime/, convex/.

## You provide
| To | What | When |
|---|---|---|
| Kritazya | Hub interface implementation (S6): `fake_hub.py` in Phase 1, real devices + hub in Phase 2; catalog with `default_limits` | Phase 1–2 |
| Judges | Every screen | Phase 2–4 |

## You consume
REST (S1) via `src/mocks` until Suyog's API is up · SpacetimeDB bindings + seed rows (S3) from Kritazya · contracts.

## Phase tasks
**Phase 0** — [ ] FSTC / ENERGY STAR figures for each catalog type
**Phase 1 (12–2 AM)**
- [ ] `equipment_catalog.json` with `default_limits` + `source_note`; `fake_hub.py` (interface from CONTRACTS.md section 8)
- [ ] Interfaces + test skeletons for devices, hub, customers
- [ ] Vite app; generated types (OpenAPI + WS schema + SpacetimeDB bindings); `src/data` hooks with the SpacetimeDB / `/ws` switch; `src/mocks`
- [ ] Shells: Builder, Live, Agent Network, Proof, chat drawer; Static Web App skeleton deploy
**Phase 2 (2–9 AM)**
- [ ] Devices + power models (fixed, cycling, demand_driven, job; thermal if time), seeded customers with crowd multiplier, hub (report, deliver, log),
      delay / reduce / restore / start handling, determinism test
- [ ] Builder complete (incl. location, preferences, Claude's authority) · Live floor + hub tile · two-lane chart · KPI row · clock + surge (SpacetimeDB `request_surge`) · context strip
**Phase 3 (9 AM–3 PM)**
- [ ] Decision feed + undo · escalation card (all states) · Agent Network screen · chat drawer + proposal cards · warning banners · reduced / waiting tile states
- [ ] Simulation fixes the brain needs (pair with Kritazya)
**Phase 4 (3–9 PM)** — [ ] Proof screen + Replay month animation · "measured (scaled)" and hardware badges · polish
**Phase 5 (9 PM–4 AM)** — [ ] `DEMO_MODE` preset kitchen · lead 5 clean runs · record and edit the 3–5 min video · Static Web Apps release

## Definition of done (your scope)
Same seed → identical simulation · power never negative or above rated · browser computes nothing but formatting ·
every message type rendered · works over SpacetimeDB and `/ws` · labels on every data source.

## Session starter
```
ROLE = ashirwad. Read CLAUDE.md, docs/team/ASHIRWAD.md, docs/ARCHITECTURE.md, docs/CONTRACTS.md, and the design doc for
today's task (SIMULATION / UI / AZURE). Stay inside my folders. Task: <task>. Restate in ≤5 lines with files and gate; plan if >50 lines.
```
