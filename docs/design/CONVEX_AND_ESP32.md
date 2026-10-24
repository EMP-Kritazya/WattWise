# Design: Convex and the ESP32 hub (owner: Suyog)

Convex holds what is a record or a device: kitchens, decisions, commands, readings, device map, hubs, proposals, escalations,
bills, backtest results, per-device 15-min blocks, hourly context snapshots. It is also the bridge to a real ESP32.

## Principles
- Load-bearing, not a side cache (Convex track ask): devices, commands, proposals and records really live here.
- Durable, not live: nothing here is read every tick by the UI (that's SpacetimeDB).
- The bridge is the hub swap: the browser hub's readings relayed by the runtime (`HARDWARE=sim_bridge`) and a real ESP32
  (`HARDWARE=esp32`) use the same functions and the same Command / Reading shapes as the hub protocol.
- Fail safe both ways (below). Fallback `STORE=memory` with the same interface.

## Tables and functions
CONTRACTS.md section 6. Python side: Convex Python client (`pip install convex`), writes batched once per real second.

## ESP32 hub
| Item | Plan |
|---|---|
| Library | `convex-esp32` (alpha): reactive queries, mutations over one TLS WebSocket |
| Board | ESP32-S3 with PSRAM preferred; Arduino-ESP32 core 3.2+; ArduinoJson 7 |
| Limits | 12 subscriptions, 8 in-flight requests, one TLS session; narrow queries, small payloads |
| Loads | 2 small 5–12 V fans / LED strips via MOSFET modules; INA219 for current. Nothing mains powered |
| Venue | No soldering: breakouts with headers, breadboard, jumpers |
| Mapping | `device_map`: hub_id + channel → device_id + `scale` (bench W → kitchen kW); UI says "measured (scaled)" |
| Flow | ESP32 subscribes `commands:forDevice(hub_id)` → executes → `commands:ack`; INA219 → `devices:report` → runtime → `ingest_reading()` |
| Fail safe | ESP32: no Convex contact 30 s → loads back to normal. Runtime: no reading 30 s → device back to simulated + `hub_offline` |
| Start | Bench test in Phase 2; `sim_bridge` test before real loads; real loads only after Gate 3 |
Kritazya has ESP32 firmware experience and can pair on `firmware/` if Suyog is overloaded.
