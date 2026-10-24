# convex/ — durable records + ESP32 bridge (owner: Suyog)

Tables and functions: `docs/CONTRACTS.md` §6. Validators mirror §1 shapes (`validators.ts`); the runtime's writes live in
`writes.ts` and are reachable one by one (`decisions:record`, …) or batched (`batch:apply`, one call per real second).
`_generated/` is written by the Convex CLI: never hand-edit it.

```bash
npm install                      # repo root (package.json); node_modules/ is gitignored
npx convex dev                   # push + watch; writes CONVEX_URL to .env.local (gitignored)
npx convex run devices:mapChannel '{"row": {"hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "scale": 1000}}'
```

Backend: `STORE=convex CONVEX_URL=https://<deployment>.convex.cloud` (and `HARDWARE=sim_bridge` to relay the browser hub's
mapped devices through `devices:report` → `devices:latest`). Convex unreachable → memory store + `store_down` warning.
Live checks: `CONVEX_TEST_URL=<url> pytest tests/runtime/test_convex_store.py -k live` (writes fixture rows to that deployment).

Not in §6 yet (contract questions): `batch:apply`, `kitchens:record`, `escalations:record`, `deviceBlocks:record`,
`contextSnapshots:record`, `devices:latest`, `devices:map`, `devices:mapChannel`.
