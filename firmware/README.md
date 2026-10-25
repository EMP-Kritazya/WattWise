# WattWise ESP32 hub

A real ESP32-S3 replaces two kitchen devices in the `with` lane. It reads two small DC loads with INA219s, switches them
through MOSFET modules, and talks to Convex only, through Convex's alpha library
[convex-esp32](https://github.com/get-convex/convex-esp32). Design: `docs/design/CONVEX_AND_ESP32.md`. Shapes: CONTRACTS.md
§1 (Command, CommandAck, Reading) and §6.

| Every | Call | What |
|---|---|---|
| change | `commands:forDevice({hub_id})` (subscription) | runs each queued Command on its channel, then `commands:ack({command_id, ok, applied_value, reason})` |
| change | `devices:map()` (subscription) | rows with this `HUB_ID`: channel → `device_id` + `scale` |
| 2 s per mapped channel | `devices:report({reading})` | `raw_w` from the INA219, `scale` from `device_map`, `power_kw = raw_w × scale / 1000` |
| 5 s | `hubs:heartbeat({hub_id})` | liveness |

**Fail safe:** 30 s without a successful Convex round trip (a heartbeat or report answered, or a subscription update) →
both channels go back to normal (on, 100 %). The runtime does the same from its side: no new reading for 30 s → that device
is simulated again and viewers get `hub_offline`.

## Parts (no soldering)

- ESP32-S3 DevKitC-1, with PSRAM if possible (N8R2 / N16R8), headers already on
- 2 × INA219 breakout with pin headers and screw terminals
- 2 × **logic-level** MOSFET module that switches fully at 3.3 V (for example D4184 / AOD4184 or IRLZ44N modules).
  IRF520 modules do not turn fully on at 3.3 V.
- 2 × 5–12 V DC fan or LED strip (< 1 A each), a 5–12 V DC supply for them, breadboard, jumpers.
  **Nothing mains powered.**

## Wiring

```
             12 V supply (+) ───────────────┬───────────────────────────┐
                                            │                           │
                                     INA219 #0 VIN+              INA219 #1 VIN+
                                     INA219 #0 VIN- ── fan 0 (+) INA219 #1 VIN- ── fan 1 (+)
                                                       fan 0 (−) ── MOSFET #0 V+/LOAD+   fan 1 (−) ── MOSFET #1 LOAD+
                                                                    MOSFET #0 V−/LOAD− ┐              MOSFET #1 LOAD− ┐
             12 V supply (−) ─────────────────────────────────────────────────────────┴─────────────────────────────┴── GND
                                                                                                                         │
 ESP32-S3                                                                                                                │
   GPIO 4  ── MOSFET #0 SIG/PWM          GPIO 5  ── MOSFET #1 SIG/PWM                                                     │
   GPIO 8  ── INA219 #0 SDA              GPIO 17 ── INA219 #1 SDA      (each INA219 on its own I2C bus,                  │
   GPIO 9  ── INA219 #0 SCL              GPIO 18 ── INA219 #1 SCL       so both keep address 0x40: no pads to solder)    │
   3V3     ── both INA219 VCC                                                                                            │
   GND     ── both INA219 GND, both MOSFET GND ──────────────────────────────────────────────────────────────────────────┘
```

The INA219 sits on the high side (supply → INA219 → load), and the MOSFET switches the low side of the load. The supply
ground and the ESP32 ground are joined. Fans are driven with 25 kHz PWM. Pins can be changed with build flags
(`CH0_PWM_PIN`, `CH1_PWM_PIN`, `I2C0_SDA`, `I2C0_SCL`, `I2C1_SDA`, `I2C1_SCL`).

A channel whose INA219 is missing still switches its load but sends no readings, so the runtime keeps that device simulated.
The serial log says `INA219 MISSING`.

## Flash

1. Install PlatformIO (the VS Code extension, or `pip install platformio`).
2. `cp include/secrets.example.h include/secrets.h` and fill in the WiFi SSID and password and the deployment's
   **`.convex.cloud`** URL (not `.convex.site`). `secrets.h` is gitignored.
3. Set `HUB_ID` in `platformio.ini` if it isn't `esp32_1`. `SIM_SPEED` must match the clock speed of the demo (120 by default).
4. Plug the board in over USB, then run:
   ```bash
   cd firmware && pio run -e esp32s3 -t upload && pio device monitor
   ```
   Use `-e esp32s3_nopsram` on a board without PSRAM. The first build downloads Arduino-ESP32 core 3.2 (pioarduino platform).
5. The log should show: `wifi <ip>` → `time 2026-…Z` → `convex connected` → `channel 0 = dishwasher_1`, and then
   commands as they come in.

## device_map for the demo kitchen

Each channel is one row: `{hub_id, channel, device_id, scale}`. `scale` turns bench watts into kitchen kW: with `scale: 1000`,
a fan drawing 5.8 W reads as a 5.8 kW device. Set the rows once per demo kitchen with `devices:mapChannel`. It replaces the row
for the same hub_id and channel.

```bash
npx convex run devices:mapChannel '{"row": {"hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "scale": 1000}}'
```

```bash
npx convex run devices:mapChannel '{"row": {"hub_id": "esp32_1", "channel": 1, "device_id": "hvac_1", "scale": 1000}}'
```

Pick `scale` so that the load's normal draw lands near the device's `rated_kw`: `scale = rated_kw × 1000 / bench_W`.
Only map devices that are in the kitchen's roster. The runtime ignores rows for other devices, and the board acks their
commands with `unknown_device`. The board picks up map changes live, and the runtime reloads them on the next kitchen build.

Then start the backend with `HARDWARE=esp32 STORE=convex`. The runtime enqueues every `with`-lane Command for a mapped device
with `hub_id: "esp32_1"`, reads the board's Readings back (`devices:latest`), and hands them to the engine with
`ingest_reading`. That device becomes `source: measured`, which the UI labels "measured (scaled)", and the lane's HubReport
becomes `mixed`.

## How each Command runs (CONTRACTS.md §1)

| action | on the channel | ack |
|---|---|---|
| `on` | on at its current % | `ok`, `applied_value = value` |
| `off` | off | `ok`, or `ok: false, reason: already_off` if it isn't running |
| `restore` | normal: on, 100 % | `ok` |
| `reduce` (value %) | on at value %, clamped to `MIN_DUTY_PCT`–100 (a fan stalls below ~20 %) | `ok`, `applied_value` = the % actually set, `reason: out_of_range` when clamped |
| `start` | on (ends a hold) | `ok`, or `ok: false, reason: job_running` if it is already running |
| `delay` (value min) | off for `value × 60 / SIM_SPEED` real seconds, then normal; replaces any hold already running | `ok`, `applied_value = value` |
| any, for an unmapped device | nothing | `ok: false, reason: unknown_device` |

Each command runs once. The board keeps every acked id while `forDevice` still lists it, and it re-sends the ack after
5 s if needed (it never runs the command again). It forgets the id once Convex drops it, because ids restart with
every kitchen build.

## Demo checks

- **Command → fan:** an owner command (dashboard or ASI:One) reaches Convex at the runtime's next store flush (once per real
  second). It then arrives over the open subscription, so the fan changes within about a second.
- **Unplug WiFi** (or switch off the access point): after 30 s the serial log shows `FAIL SAFE` and both loads are back at
  100 %. Meanwhile the runtime emits `hub_offline` and simulates the device again.
- **UI:** the mapped device shows "measured (scaled)" while readings flow.

## Known limits

- A `delay` hold runs in real time at `SIM_SPEED`. Pausing or changing the clock speed does not stretch it.
- The bench load stands in for power, not job phases. On the board, "running" just means the load is on.
- Commands queued while the board was offline run in order when it reconnects, so the last one wins.
- Reading `ts` is real UTC from SNTP. The board has no sim time. It sends no readings until SNTP has synced.
