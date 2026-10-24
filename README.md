# WattWise

Keeps a restaurant's electricity peak under control without stopping service.

**Team:** Kritazya Upreti, Suyog, Ashirwad · **Event:** Cal Hacks 13.0

- Owner builds the kitchen: picks equipment, counts, each device's importance (always on / flexible / deferrable) and a peak cap in kW.
- Every device reports to one hub box (simulated ESP32). The engine forecasts, decides and acts inside the owner's rules.
- Claude explains every decision and answers questions; it never decides.
- Proof: replay of historical restaurant data with vs. without WattWise on a real tariff.

## Run
> Fill in during the hackathon.
```
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn api.main:app --reload
cd frontend && npm install && npm run dev
```
`.env` (never committed): `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `DATABASE_URL`, `DEMO_MODE`, `KITCHEN_IMPL=fake|real`.

Start with `CLAUDE.md`, then `docs/ARCHITECTURE.md`.

Data credits: NREL ComStock End-Use Load Profiles · OpenEI Utility Rate Database · FSTC / ENERGY STAR appliance data.
