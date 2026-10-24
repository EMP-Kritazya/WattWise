"""The clock and the run loop (ARCHITECTURE.md flow 1 + Time, docs/design/API.md "Run loop").

One tick = 1 simulated minute, sent every `0.5 s × 120 / speed` real seconds (speeds 1, 30, 120, 600). Each tick:
surges + physical inputs + the Commands queued last tick → `HubLink.tick` (sim_tick → hub_report) → `step(1, report)` on
both lanes → `compare_lanes` → live publish → the lanes' `new_commands` queued for tick n + 1 → store buffer (written at
most once per real second). The loop computes no number and never waits on Claude, agents, Convex or SpacetimeDB: live
calls are queued (`LivePublisher`), store writes run in a worker thread, surge reads are time-boxed. It only waits for the
hub, which is the simulation itself (`hub_waiting` / `sim_host_offline` pause the clock).

`tick_once()` is the whole tick; `_run()` paces it while playing. Tests call `tick_once()` directly (`autorun=False`).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from agent.templates import explain_decision
from runtime.device_bridge import BlockAverager, DeviceBridge
from runtime.escalations import Escalations
from runtime.hub_link import HubLink, TickAborted
from runtime.events import SurgeQueue
from runtime.lanes import LANES
from runtime.live_port import LivePublisher
from store import Store

TICK_BASE_S = 0.5  # real seconds per tick at 120×
DEFAULT_SPEED = 120
SPEEDS = (1, 30, 120, 600)
STORE_FLUSH_S = 1.0
KITCHEN_ID = "k_01"  # one kitchen per process (demo)
# CONTRACTS.md §1 Context: crowd_effect → crowd multiplier (the engine's fixed table; the simulation needs it in sim_tick).
CROWD_MULTIPLIER = {"none": 1.00, "small": 1.10, "medium": 1.25, "large": 1.40}
DEFAULT_CROWD_MULTIPLIER = 1.0

log = logging.getLogger("runtime.loop")


def tick_interval_s(speed: int) -> float:
    return TICK_BASE_S * 120 / speed


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hhmm(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


class RunLoop:
    def __init__(
        self,
        *,
        service: Any,
        hub: HubLink,
        live: LivePublisher,
        store: Store,
        start_sim_ts: str,
        autorun: bool = True,
        publish_ws: Callable[[dict], None] | None = None,
        demo_mode: bool = False,
        bridge: DeviceBridge | None = None,
    ):
        self.service = service  # api.service.KitchenService: lanes, tariff, catalog, lock
        self.hub = hub
        self.live = live
        self.store = store
        self.bridge = bridge or DeviceBridge("off", store)  # HARDWARE=sim_bridge|esp32: mapped devices through Convex
        self.blocks = BlockAverager()  # closed 15-min device_blocks, every HARDWARE mode
        self.autorun = autorun
        self._start = _parse_ts(start_sim_ts)
        self.surges = SurgeQueue()
        self.playing = False
        self.speed = DEFAULT_SPEED
        self.slowed_reason: str | None = None  # escalation slowdown: not built (open question Q1 for Kritazya)
        self.hub_status: str | None = hub.paused_reason  # hub_waiting | sim_host_offline | None, from HubLink.on_status
        self.context: dict | None = None  # latest merged Context (posts merge)
        self.tick_id = 0
        self._commands: list[dict] = []  # delivered in the next sim_tick
        self._owner_command_ids: set[str] = set()  # queued at once; skipped if the engine echoes them in new_commands
        self._build_count = 0
        self._store_buffer: list[Callable[[], None]] = []
        self._store_task: asyncio.Future | None = None
        self._last_store_flush = time.monotonic()
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        # Claude resolves the engine's escalations; `escalations.agent` is set once the agent exists (api/main.py).
        self.escalations = Escalations(service=service, live=live, clock=lambda: self.sim_ts,
                                       on_pause=self._on_escalation_pause, publish_ws=publish_ws, demo_mode=demo_mode)

    # ------------------------------------------------------------ clock

    @property
    def sim_ts(self) -> str:
        """Start of the next tick's minute (= end of the last stepped one)."""
        return _iso(self._start + timedelta(minutes=self.tick_id))

    @property
    def paused_reason(self) -> str | None:
        """The hub first (nothing can tick without it), then the demo-mode escalation pause."""
        return self.hub_status or self.escalations.paused_reason

    def clock_state(self) -> dict:
        return {"playing": self.playing, "speed": self.speed, "sim_ts": self.sim_ts, "tick_id": self.tick_id,
                "paused_reason": self.paused_reason, "slowed_reason": self.slowed_reason}

    def _publish_clock(self) -> None:
        self.live.send("set_clock", self.clock_state(), "connected" if self.hub.connected else "offline")

    async def control(self, action: str, speed: int | None = None) -> dict:
        """`POST /api/sim/control` → ClockState."""
        if speed is not None:
            if speed not in SPEEDS:
                raise ValueError(f"speed {speed}; expected one of {SPEEDS}")
            self.speed = speed
        if action == "play":
            self.service.require_kitchen()
            await self.restore_build()
            self.playing = True
            if self.autorun:
                self._ensure_task()
        elif action == "pause":
            self.playing = False
        elif action == "reset":
            self.playing = False
            await self.hub.send_control("reset", self.speed, self.paused_reason)
            await self.build(self.service.lanes.config)
            return self.clock_state()
        else:
            raise ValueError(f"unknown clock action {action!r}")
        await self.hub.send_control(action, self.speed, self.paused_reason)
        self._publish_clock()
        self._poke()
        return self.clock_state()

    def on_hub_status(self, paused_reason: str | None) -> None:
        """HubLink.on_status: hub_waiting / sim_host_offline pause the clock; None resumes it."""
        self.hub_status = paused_reason
        self._publish_clock()
        self._poke()

    def on_host(self, connected: bool) -> None:
        self._poke()

    def _on_escalation_pause(self) -> None:
        """DEMO_MODE=1: the clock pauses while Claude decides an escalation and resumes after."""
        self._publish_clock()
        self._poke()

    # ------------------------------------------------------------ kitchen

    async def build(self, config: dict) -> dict:
        """`POST /api/kitchen`: both lanes → `sim_build` → `reset_all` → first publish (clock at tick 0, context)."""
        result = self.service.build_kitchen(config)  # RuleError → nothing below happens
        self._build_count += 1
        self.playing = False
        self.tick_id = 0
        self._commands = []
        self._owner_command_ids = set()
        self.surges.reset()
        self.escalations.reset()
        self.blocks.reset()
        devices = self.service.get_kitchen()["devices"]
        await self.bridge.reset({d["device_id"] for d in devices})
        await self.hub.send_build(KITCHEN_ID, config, self.service.catalog(), devices, self.service.lanes.seed,
                                  _iso(self._start))
        self.live.send("reset_all")
        self._publish_clock()
        if self.context is not None:
            # New lanes start without context: hand them the last known until the Concierge's next round.
            self.service.post_context(copy.deepcopy(self.context))
            self.live.send("publish_context", copy.deepcopy(self.context))
        return result

    async def restore_build(self) -> bool:
        """A kitchen restored from the store at startup has lanes but no `sim_build` yet: send it once, unchanged.

        Without this, play on a restored kitchen ticks a hub that was never built. No-op after any `build`.
        """
        if self._build_count or not self.service.lanes:
            return False
        self._build_count += 1
        devices = self.service.get_kitchen()["devices"]
        await self.bridge.reset({d["device_id"] for d in devices})
        await self.hub.send_build(KITCHEN_ID, self.service.lanes.config, self.service.catalog(), devices,
                                  self.service.lanes.seed, _iso(self._start))
        return True

    # ------------------------------------------------------------ owner + agents

    def owner_command(self, device_id: str, body: dict) -> dict:
        """`POST /api/devices/{id}/command`: the engine's owner Command goes out in the next sim_tick."""
        command = self.service.device_command(device_id, body)
        self._commands.append(command)
        self._owner_command_ids.add(command["command_id"])
        return command

    def customer_event(self, body: dict) -> dict:
        """`POST /api/events/customers` → a surge in the next sim_tick."""
        self.surges.add(body["customers"], body["duration_min"])
        return {"ok": True}

    def schedule_customer_event(self, payload: dict) -> None:
        """A confirmed `customer_event` proposal: a surge in the sim_tick of `start_sim_ts` (the next one if past)."""
        self.surges.add_at(payload["start_sim_ts"], payload["customers"], payload["duration_min"])

    def post_context(self, body: dict) -> dict:
        """`POST /api/context`: stamp `ts` in sim time, merge, hand to both lanes, publish. Numbers pass unchanged."""
        stamped = {**body, "ts": self.sim_ts}
        self.service.post_context(stamped)
        self.context = {**(self.context or {}), **copy.deepcopy(stamped)}
        self.live.send("publish_context", copy.deepcopy(self.context))
        return {"ok": True}

    def set_crowd_effect(self, body: dict) -> dict:
        crowd_effect = self.service.set_crowd_effect(body)
        self.context = {**(self.context or {}), "crowd_effect": crowd_effect}
        self.live.send("publish_context", copy.deepcopy(self.context))
        return {"ok": True}

    def log_agent(self, entry: dict) -> dict:
        self.live.send("log_agent", copy.deepcopy(entry))
        return {"ok": True}

    # ------------------------------------------------------------ the tick

    def inputs(self, sim_ts: str) -> dict:
        """`sim_tick.inputs` for the minute starting at `sim_ts`: physical facts from the latest context + opening hours.
        No weather for that hour → `outdoor_temp_c: null` (the simulation uses its built-in curve)."""
        ctx = self.context or {}
        temp = None
        hour = sim_ts[:13]
        for row in (ctx.get("weather") or {}).get("hourly", []):
            if row["ts"][:13] == hour:
                temp = row["temp_c"]
                break
        crowd = (ctx.get("crowd_effect") or {}).get("value")
        return {"outdoor_temp_c": temp, "crowd_multiplier": CROWD_MULTIPLIER.get(crowd, DEFAULT_CROWD_MULTIPLIER),
                "is_open": self._is_open(sim_ts)}

    def _is_open(self, sim_ts: str) -> bool:
        hours = (self.service.lanes.config or {}).get("operating_hours")
        if not hours:
            return True
        local = _parse_ts(sim_ts).astimezone(ZoneInfo(self.service.tariff["timezone"]))
        now, opens, closes = local.hour * 60 + local.minute, _hhmm(hours["open"]), _hhmm(hours["close"])
        return opens <= now < closes if opens < closes else (now >= opens or now < closes)

    async def tick_once(self) -> bool:
        """One sim minute. False when the tick was abandoned (kitchen rebuilt meanwhile) or the engine failed."""
        build = self._build_count
        tick_id, sim_ts = self.tick_id + 1, self.sim_ts
        for request_id in self.surges.add_requests(await self.live.read_surges()):
            self.live.send("consume_surge", request_id)
        surges, commands = self.surges.drain(sim_ts), self._commands
        self._commands = []
        try:
            report = await self.hub.tick(tick_id, sim_ts, surges, self.inputs(sim_ts), commands)
        except TickAborted:
            return False
        if build != self._build_count:
            return False
        self.tick_id = tick_id  # the simulation has stepped this minute, whatever the engine does with it
        try:
            with self.service.lock:
                report = self.bridge.before_step(report, self.service.lanes["with"])  # Readings → ingest_reading
                states = self.service.lanes.step(1, report)
                comparison = self.service.lanes.compare(states)
        except Exception:
            log.exception("engine step failed at tick %s; the clock goes on", tick_id)
            self._publish_clock()
            return False
        self._queue_commands(states)
        self._publish(tick_id, states, comparison)
        self.escalations.after_tick()
        self.bridge.start()
        self.bridge.after_step(report)
        self._buffer_records(states, report, self.blocks.add(report, self.bridge.measured_kw()))
        self._maybe_flush_store()
        return True

    def _queue_commands(self, states: dict[str, dict]) -> None:
        for lane in LANES:
            for command in states[lane]["new_commands"]:
                if command["command_id"] in self._owner_command_ids:
                    continue  # already delivered when the owner clicked
                self._commands.append(command)

    def _publish(self, tick_id: int, states: dict[str, dict], comparison: dict) -> None:
        self.live.send("publish_ticks", tick_id, states, comparison)
        for lane in LANES:
            names = {d["device_id"]: d["name"] for d in states[lane]["hub"]["devices"]}
            for decision in states[lane]["new_decisions"]:
                text = explain_decision(decision, names.get(decision["device_id"], decision["device_id"]))
                self.live.send("publish_feed", lane, decision, text, "template")
            for escalation in states[lane]["new_escalations"]:
                self.escalations.opened(escalation)  # published, then Claude decides in the background
        self._publish_clock()

    # ------------------------------------------------------------ store

    def _buffer_records(self, states: dict[str, dict], report: dict, closed_blocks: list[dict]) -> None:
        for lane in LANES:
            st = states[lane]
            names = {d["device_id"]: d["name"] for d in st["hub"]["devices"]}
            records = [
                {**d, "lane": lane, "explanation": explain_decision(d, names.get(d["device_id"], d["device_id"])),
                 "explanation_source": "template"}
                for d in st["new_decisions"]
            ]
            if records:
                self._store_buffer.append(lambda records=records: self.store.record_decisions(records))
            for command in st["new_commands"]:
                # hub_id: the Convex hub of a mapped with-lane device (device bridge); simulated devices have none.
                hub_id = self.bridge.track_command(command, lane)
                self._store_buffer.append(lambda c=command, lane=lane, h=hub_id: self.store.record_command(c, lane, h))
        self._store_buffer.extend(self.bridge.ack_writes(report))  # after this tick's enqueues
        if closed_blocks:
            self._store_buffer.append(lambda: self.store.record_device_blocks(closed_blocks))

    def _maybe_flush_store(self) -> None:
        if time.monotonic() - self._last_store_flush >= STORE_FLUSH_S:
            self._flush_store_soon()

    def _flush_store_soon(self) -> asyncio.Future | None:
        if not self._store_buffer or (self._store_task is not None and not self._store_task.done()):
            return self._store_task
        writes, self._store_buffer = self._store_buffer, []
        self._last_store_flush = time.monotonic()

        def write_all() -> None:
            for write in writes:
                try:
                    write()
                except Exception:
                    log.exception("store write failed")  # Convex unreachable is handled inside ConvexStore (store_down)

        self._store_task = asyncio.ensure_future(asyncio.to_thread(write_all))
        return self._store_task

    async def flush(self) -> None:
        """Send every queued live call and store write now (tests, shutdown)."""
        while self._store_buffer or (self._store_task is not None and not self._store_task.done()):
            task = self._flush_store_soon()
            if task is not None:
                await task
        await self.live.flush()

    # ------------------------------------------------------------ pacing

    def _runnable(self) -> bool:
        return (self.playing and self.hub.connected and bool(self.service.lanes)
                and self.escalations.paused_reason is None)

    def _poke(self) -> None:
        if self._wake is not None:
            self._wake.set()

    def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._wake = asyncio.Event()
            self._task = asyncio.create_task(self._run(), name="run-loop")

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            while not self._runnable():
                self._wake.clear()
                await self._wake.wait()
            started = loop.time()
            try:
                await self.tick_once()
            except Exception:
                log.exception("tick failed; the loop goes on")
            while self._runnable():  # wait out this tick's interval at the current speed
                remaining = started + tick_interval_s(self.speed) - loop.time()
                if remaining <= 0:
                    break
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), remaining)
                except asyncio.TimeoutError:
                    pass

    async def stop(self) -> None:
        await self.escalations.stop()
        await self.bridge.stop()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        await self.flush()
        await self.live.stop()
