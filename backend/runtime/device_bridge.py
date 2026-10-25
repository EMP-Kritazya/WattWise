"""Device bridge: the hub swap through Convex (ARCHITECTURE.md "Hub swap", docs/design/CONVEX_AND_ESP32.md, CONTRACTS.md §6).

`HARDWARE=off` (default): nothing is bridged. `HARDWARE=sim_bridge`: for every `device_map` device, the browser hub's
`with`-lane reading goes out through `devices:report` and is read back from the store (`devices:latest`) as a Reading,
which is handed to `ingest_reading` on the `with` lane before a later step; that lane's Commands for mapped devices are
enqueued with their `hub_id` (`commands:enqueue`) and the hub's CommandAcks for them go to `commands:ack`. This proves the
drop-in without hardware. `HARDWARE=esp32`: the same, except the ESP32 reports and acks itself; the `with` HubReport is
marked `source: "mixed"` while a measured device is live. In `sim_bridge` the relayed numbers are still the simulation's,
so nothing is labelled measured (contract question for Kritazya).

No new reading for a mapped device for 30 real seconds → that device falls back to simulated (no more `ingest_reading`)
and one `hub_offline` warning `{device_id, hub_id}` goes out. A clock pause longer than that does not count.

Liveness decided in Convex (`convex/liveness.ts`, a cron every 10 s; the memory store mirrors it), read every
`LIVENESS_POLL_S` by the background task, `esp32` only (in `sim_bridge` the browser hub is the hub and no board heartbeats):
- `hubs:status` says a hub is offline (no heartbeat for 30 s) → each of its devices goes offline as above, one
  `hub_offline` warning each. A new reading brings it back.
- `commands:failed` lists a bridged command (nacked, or not acked 15 s after enqueue) → it is enqueued once more, same
  command; failed again → its device falls back to simulated until the next kitchen build (no more readings ingested,
  its Commands no longer go to the hub) and one `hub_offline` warning goes out.

The tick path (`before_step`, `after_step`, `ack_writes`) does no I/O beyond store calls that only queue (the Convex store
batches; the memory store is in process). Readings are read back by a background task (`poll_once` every `POLL_S`).

`BlockAverager` is the 15-min `device_blocks` writer: whatever `HARDWARE` is, every device of both lanes gets one row per
closed block, `avg_kw` = mean of the hub's per-minute `power_kw` over the block (rounded to 3 decimals, as the fixtures).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from store import Store

log = logging.getLogger("runtime.device_bridge")

MODES = ("off", "sim_bridge", "esp32")
HUB_TIMEOUT_S = 30.0
POLL_S = 0.5
LIVENESS_POLL_S = 5.0
BLOCK_MIN = 15


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_OFFLINE_WHY = {
    "reading": "No reading from {hub_id} for {device_id} for 30 s. It is simulated again.",
    "hub": "{hub_id} has not been seen for 30 s. {device_id} is simulated again.",
    "command": "{hub_id} did not execute a command for {device_id}, even after a retry. It is simulated again.",
}


def hub_offline_warning(device_id: str, hub_id: str, why: str = "reading") -> dict:
    return {
        "type": "warning",
        "code": "hub_offline",
        "message": _OFFLINE_WHY[why].format(device_id=device_id, hub_id=hub_id),
        "data": {"device_id": device_id, "hub_id": hub_id},
    }


class DeviceBridge:
    def __init__(
        self,
        mode: str,
        store: Store,
        *,
        on_warning: Callable[[dict], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        timeout_s: float = HUB_TIMEOUT_S,
        poll_s: float = POLL_S,
        liveness_poll_s: float = LIVENESS_POLL_S,
    ):
        if mode not in MODES:
            raise ValueError(f"HARDWARE={mode!r}; expected one of {MODES}")
        self.mode = mode
        self.store = store
        self._on_warning = on_warning
        self._clock = clock
        self._wall_clock = wall_clock  # real epoch s: `commands:failed.since_ms` is Convex `_creationTime`
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._liveness_poll_s = liveness_poll_s
        self._map: dict[str, dict] = {}  # device_id → device_map row
        self._bridged: dict[str, str] = {}  # command_id → hub_id (with-lane commands enqueued for a hub)
        self._latest: dict[str, dict] = {}  # device_id → newest Reading read back
        self._ingested_ts: dict[str, str] = {}  # device_id → ts of the last Reading handed to the engine
        self._last_seen: dict[str, float] = {}  # device_id → clock() when a new Reading was last read back
        self._status: dict[str, str] = {}  # device_id → waiting | live | offline
        self._last_step_at: float | None = None
        self._sent: dict[str, tuple[dict, str, str]] = {}  # esp32: command_id → (command, lane, hub_id)
        self._failed_rows: dict[str, int] = {}  # command_id → failed rows already handled (1: retried, 2: gave up)
        self._dropped: set[str] = set()  # devices simulated again after a command failed twice (until the next build)
        self._since_ms = 0.0  # kitchen build time, real epoch ms
        self._last_liveness_at: float | None = None
        self._task: asyncio.Task | None = None

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def measured_kw(self) -> dict[str, float]:
        """device_id → kW of every device fed by a live real reading (esp32 only: sim_bridge numbers stay simulated)."""
        if self.mode != "esp32":
            return {}
        return {d: self._latest[d]["power_kw"] for d, s in self._status.items() if s == "live" and d in self._latest}

    def mapped(self) -> dict[str, dict]:
        return copy.deepcopy(self._map)

    # ------------------------------------------------------------ setup

    def load_map(self, rows: list[dict], device_ids: set[str] | None = None) -> None:
        """Mapped devices of this kitchen (`device_ids` = its roster; None keeps every row). Resets every timer."""
        self._map = {r["device_id"]: dict(r) for r in rows if device_ids is None or r["device_id"] in device_ids}
        self._bridged, self._latest, self._ingested_ts = {}, {}, {}
        now = self._clock()
        self._last_seen = {d: now for d in self._map}
        self._status = {d: "waiting" for d in self._map}
        self._last_step_at = None
        self._sent, self._failed_rows, self._dropped = {}, {}, set()
        self._since_ms = self._wall_clock() * 1000
        self._last_liveness_at = None

    async def reset(self, device_ids: set[str] | None = None) -> None:
        """New kitchen: reload `device_map` from the store (Convex: a query, so off the event loop)."""
        if not self.enabled:
            return
        try:
            rows = await asyncio.to_thread(self.store.device_map)
        except Exception:
            log.exception("device_map could not be read; nothing is bridged")
            rows = []
        self.load_map(rows, device_ids)
        log.info("device bridge (%s): %s", self.mode, sorted(self._map) or "no mapped devices")

    def hub_id_for(self, lane: str, device_id: str) -> str | None:
        """The Convex hub a Command goes to (`commands:enqueue.hub_id`): mapped `with`-lane devices only."""
        if not self.enabled or lane != "with" or device_id not in self._map or device_id in self._dropped:
            return None
        return self._map[device_id]["hub_id"]

    def track_command(self, command: dict, lane: str) -> str | None:
        """`hub_id_for` + remember the command so its CommandAck is relayed."""
        hub_id = self.hub_id_for(lane, command["device_id"])
        if hub_id is not None:
            self._bridged[command["command_id"]] = hub_id
            if self.mode == "esp32":
                self._sent[command["command_id"]] = (copy.deepcopy(command), lane, hub_id)
        return hub_id

    # ------------------------------------------------------------ tick path

    def before_step(self, hub_report: dict, with_kitchen: Any) -> dict:
        """Timeouts, then every Reading read back since the last tick → `with_kitchen.ingest_reading`. Returns the
        hub_report to step (esp32: the `with` HubReport's `source` is "mixed" while a measured device is live)."""
        if not self.enabled or not self._map:
            return hub_report
        now = self._clock()
        if self._last_step_at is not None and now - self._last_step_at > self._timeout_s:
            # The clock was paused: a reading gap while nothing ticks is not the hub's fault.
            self._last_seen = {d: now for d in self._last_seen}
        self._last_step_at = now
        for device_id, row in self._map.items():
            if self._status[device_id] != "offline" and now - self._last_seen[device_id] > self._timeout_s:
                self._status[device_id] = "offline"
                log.warning("hub_offline: %s on %s; back to simulated", device_id, row["hub_id"])
                self._warn(hub_offline_warning(device_id, row["hub_id"]))
        for device_id, reading in self._latest.items():
            if self._status.get(device_id) != "live" or self._ingested_ts.get(device_id) == reading["ts"]:
                continue
            self._ingested_ts[device_id] = reading["ts"]
            try:
                with_kitchen.ingest_reading(copy.deepcopy(reading))
            except Exception:
                log.exception("ingest_reading failed for %s", device_id)
        if self.measured_kw():
            hub_report = copy.deepcopy(hub_report)
            hub_report["reports"]["with"]["source"] = "mixed"
        return hub_report

    def after_step(self, hub_report: dict) -> None:
        """sim_bridge: the `with` lane's mapped devices → `devices:report` (queued by the store)."""
        if self.mode != "sim_bridge" or not self._map:
            return
        report = hub_report["reports"]["with"]
        for device in report["devices"]:
            row = self._map.get(device["device_id"])
            if row is None:
                continue
            reading = {
                "hub_id": row["hub_id"], "channel": row["channel"], "device_id": device["device_id"],
                "ts": report["ts"],
                # The bench channel's watts that would read this kitchen kW (CONTRACTS.md §1: power_kw = raw_w × scale / 1000).
                "raw_w": device["power_kw"] * 1000 / row["scale"], "scale": row["scale"], "power_kw": device["power_kw"],
            }
            try:
                self.store.report_reading(reading)
            except Exception:
                log.exception("devices:report failed for %s", device["device_id"])

    def ack_writes(self, hub_report: dict) -> list[Callable[[], None]]:
        """sim_bridge: the hub's CommandAcks for bridged Commands → `commands:ack` writes, for the loop's store buffer
        (after this tick's `commands:enqueue`, so Convex always sees a command before its ack)."""
        if self.mode != "sim_bridge":
            return []
        writes = []
        for ack in hub_report["reports"]["with"]["acks"]:
            if self._bridged.pop(ack["command_id"], None) is not None:
                writes.append(lambda a=ack: self.store.ack_command(a["command_id"], a["ok"], a["applied_value"],
                                                                   a["reason"]))
        return writes

    # ------------------------------------------------------------ read-back

    def poll_once(self) -> None:
        """Read the newest Reading of every mapped hub back from the store (blocking: call it off the event loop)."""
        now = self._clock()
        for hub_id in sorted({row["hub_id"] for row in self._map.values()}):
            try:
                readings = self.store.latest_readings(hub_id)
            except Exception:
                log.exception("devices:latest failed for %s", hub_id)
                continue
            for reading in readings:
                device_id = reading["device_id"]
                if device_id not in self._map:
                    continue
                previous = self._latest.get(device_id)
                if previous is not None and previous["ts"] == reading["ts"]:
                    continue
                self._latest[device_id] = reading
                self._last_seen[device_id] = now
                if device_id in self._dropped:
                    continue
                if self._status.get(device_id) != "live":
                    log.info("device bridge: %s live on %s", device_id, hub_id)
                self._status[device_id] = "live"
        if self.mode == "esp32" and (self._last_liveness_at is None
                                     or now - self._last_liveness_at >= self._liveness_poll_s):
            self._last_liveness_at = now
            self.check_liveness()

    def check_liveness(self) -> None:
        """esp32: Convex's liveness view → offline devices, one retry per failed command, then simulated (blocking)."""
        try:
            offline = {h["hub_id"] for h in self.store.hub_status() if h["status"] == "offline"}
        except Exception:
            log.exception("hubs:status failed")
            offline = set()
        for device_id, row in self._map.items():
            if row["hub_id"] in offline and self._status[device_id] != "offline":
                self._go_offline(device_id, "hub")
        for hub_id in sorted({hub_id for _, _, hub_id in self._sent.values()}):
            try:
                failed = self.store.failed_commands(hub_id, self._since_ms)
            except Exception:
                log.exception("commands:failed failed for %s", hub_id)
                continue
            counts: dict[str, int] = {}
            for command in failed:
                counts[command["command_id"]] = counts.get(command["command_id"], 0) + 1
            for command_id, n in counts.items():
                if command_id not in self._sent or n <= self._failed_rows.get(command_id, 0):
                    continue
                self._failed_rows[command_id] = n
                command, lane, hub_id = self._sent[command_id]
                device_id = command["device_id"]
                if device_id in self._dropped:
                    continue
                if n == 1:
                    log.warning("command %s for %s failed on %s; retrying once", command_id, device_id, hub_id)
                    try:
                        self.store.record_command(copy.deepcopy(command), lane, hub_id)
                    except Exception:
                        log.exception("retry of %s could not be enqueued", command_id)
                else:
                    self._dropped.add(device_id)
                    if self._status[device_id] != "offline":  # already warned (no reading, hub offline)
                        self._go_offline(device_id, "command")

    def _go_offline(self, device_id: str, why: str) -> None:
        hub_id = self._map[device_id]["hub_id"]
        self._status[device_id] = "offline"
        log.warning("hub_offline (%s): %s on %s; back to simulated", why, device_id, hub_id)
        self._warn(hub_offline_warning(device_id, hub_id, why))

    def start(self) -> None:
        if self.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.get_running_loop().create_task(self._run(), name="device-bridge")

    async def _run(self) -> None:
        while True:
            if self._map:
                try:
                    await asyncio.to_thread(self.poll_once)
                except Exception:
                    log.exception("device bridge poll failed")
            await asyncio.sleep(self._poll_s)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def _warn(self, message: dict) -> None:
        if self._on_warning is not None:
            try:
                self._on_warning(message)
            except Exception:
                log.exception("warning could not be delivered")


class BlockAverager:
    """Per-device 15-min blocks of both lanes from the hub's per-minute reports → closed `device_blocks` rows."""

    def __init__(self) -> None:
        self._block_start: str | None = None
        self._sums: dict[tuple[str, str], list] = {}  # (lane, device_id) → [sum_kw, minutes, measured_minutes]

    def reset(self) -> None:
        self._block_start, self._sums = None, {}

    @staticmethod
    def block_of(report_ts: str) -> str:
        """The block holding the minute that ends at `report_ts` (HubReport.ts = end of the simulated minute)."""
        start = _parse_ts(report_ts) - timedelta(minutes=1)
        return _iso(start.replace(minute=start.minute - start.minute % BLOCK_MIN, second=0, microsecond=0))

    def add(self, hub_report: dict, measured: dict[str, float] | None = None) -> list[dict]:
        """One tick of both lanes. `measured`: `with`-lane device_id → measured kW for this minute (esp32).
        Returns the rows of the block this report closed (empty while the block is still open)."""
        reports = hub_report["reports"]
        block = self.block_of(reports["with"]["ts"])
        closed = self.close() if self._block_start not in (None, block) else []
        self._block_start = block
        for lane in ("without", "with"):
            for device in reports[lane]["devices"]:
                kw = device["power_kw"]
                is_measured = lane == "with" and measured is not None and device["device_id"] in measured
                if is_measured:
                    kw = measured[device["device_id"]]
                acc = self._sums.setdefault((lane, device["device_id"]), [0.0, 0, 0])
                acc[0] += kw
                acc[1] += 1
                acc[2] += 1 if is_measured else 0
        return closed

    def close(self) -> list[dict]:
        """Rows of the open block, which is then forgotten. A kitchen rebuilt mid-block `reset`s instead (no partial row)."""
        rows = []
        for (lane, device_id), (total, minutes, measured_minutes) in self._sums.items():
            rows.append({
                "lane": lane, "device_id": device_id, "block_start": self._block_start,
                "avg_kw": round(total / minutes, 3),
                "source": "measured" if measured_minutes == minutes else "simulated",
            })
        self._sums = {}
        return rows
