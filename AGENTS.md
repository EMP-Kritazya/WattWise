# WattWise integration guidance

Read `CLAUDE.md`, `docs/ARCHITECTURE.md`, and `docs/CONTRACTS.md` before changing code. The current architecture and contracts take precedence over historical branch notes. Follow the golden rules and public engine facade imports in CLAUDE.md.

Cross-workstream integration on `engine_backend` is authorized by the user. Preserve the engine as the source of computed numbers, FastAPI as the clock, the hub as the appliance boundary, and SpacetimeDB as the main live transport (WebSocket fallback).

Use architecture-reviewer before completing a merge; contract-sync and fixture-builder are required only when shared shapes change. Do not commit secrets or datasets.
