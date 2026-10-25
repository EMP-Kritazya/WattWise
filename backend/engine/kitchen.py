"""Kitchen facade (CONTRACTS.md section 3; ENGINE.md sections 0, 7, 10, 12).

One Kitchen per lane. Plain objects in (dicts or contract models), JSON-ready dicts out. No I/O, no wall clock:
time comes only from HubReport `ts` and WarmUpHistory `end`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional

from contracts import (
    ClaudeAuthority,
    Command,
    Decision,
    Effect,
    Device,
    EquipmentType,
    Escalation,
    HubReport,
    KitchenConfig,
    Meter,
    Reading,
    Tariff,
    TickState,
    WarmUpHistory,
)

from . import rules
from .context import ContextState
from .decider import target_kw, plan, effect, reduce_forecast, totals
from .forecaster import forecast_devices
from .history import BlockHistory
from .ids import IdAllocator
from .ledger import Ledger
from .meter import BLOCK_H, MeterState
from .rules import RuleError
from .tariff import BLOCK, MINUTE, TariffView, block_start_of

LANES = ("without", "with")
DECISION_EVERY_TICKS = 5
FORECAST_BLOCKS = 8
FORECAST_HORIZON_MIN = 120


def _plain(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


# ----------------------------------------------------------------------------------------------------------------------
# equipment type facts from the catalog the runtime passes in (CONTRACTS.md section 3; ENGINE.md section 0)
# ----------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TypeFacts:
    """`category` (food-safety floor), `power_model` (crowd multiplier, job holds), `rated_kw`, `params` of one type,
    taken per kitchen from the passed catalog; the engine keeps no module-level copy and reads no files."""
    type_id: str
    name: str
    category: str
    power_model: str
    rated_kw: float
    params: Mapping[str, float] = field(default_factory=dict)


# STUB: TickState.indoor_temp_c is a required float, but a kitchen without a thermal device reports no indoor
# temperature. Until the contract says what to send, the engine falls back to this value (design question).
DEFAULT_INDOOR_TEMP_C = 22.5


def type_facts_from(catalog: Iterable[Any]) -> Mapping[str, TypeFacts]:
    """type_id -> TypeFacts for one kitchen. Entries may be EquipmentType models or plain dicts."""
    facts: dict[str, TypeFacts] = {}
    for entry in catalog:
        t = entry if isinstance(entry, EquipmentType) else EquipmentType.model_validate(_plain(entry))
        if t.type_id in facts:
            raise RuleError(f"catalog lists type {t.type_id!r} twice")
        facts[t.type_id] = TypeFacts(t.type_id, t.name, t.category, t.power_model, t.rated_kw,
                                     MappingProxyType(dict(t.params)))
    return MappingProxyType(facts)


def lookup(facts: Mapping[str, TypeFacts], type_id: str) -> TypeFacts:
    """An unknown type fails loudly (RuleError) rather than guessing a category: a guess could cross the food-safety floor."""
    try:
        return facts[type_id]
    except KeyError:
        raise RuleError(f"equipment type {type_id!r} is not in the catalog passed to the Kitchen") from None


class _Unit:
    """One device of this kitchen: roster facts + the owner's current importance and limits."""

    def __init__(self, device_id: str, n: int, facts: TypeFacts, importance: str, limits: dict) -> None:
        self.device_id = device_id
        self.n = n
        self.facts = facts
        self.importance = importance
        self.limits = limits


class Kitchen:
    # ------------------------------------------------------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------------------------------------------------------
    def __init__(self, config: Any, tariff: Any, catalog: Any, control: str, seed: int,
                 ids: Optional[IdAllocator] = None) -> None:
        if control not in LANES:
            raise ValueError(f"control must be 'without' or 'with', got {control!r}")
        self.config = KitchenConfig.model_validate(_plain(config))
        self.tariff = Tariff.model_validate(_plain(tariff))
        if self.config.tariff_id != self.tariff.tariff_id:
            raise ValueError(f"config tariff_id {self.config.tariff_id!r} != tariff {self.tariff.tariff_id!r}")
        self.control = control
        self.seed = seed
        self.ids = ids if ids is not None else IdAllocator()
        self._tariff = TariffView(self.tariff)
        self._units = self._build_roster(self.config, type_facts_from(catalog))

        self.peak_mode = self.config.peak_mode
        self.peak_cap_kw = self.config.peak_cap_kw
        self.authority = self.config.authority.model_dump(mode="json")
        self.preferences = self.config.owner_preferences

        self._meter = MeterState(self._tariff)
        self._history = BlockHistory()
        self._context = ContextState()
        self._now: Optional[datetime] = None
        self._tick_id: Optional[int] = None
        self._stepped = False
        self._warmed_up = False
        self._devices: dict[str, dict] = {}
        self._total_kw = 0.0
        self._indoor_temp_c: Optional[float] = None
        self._pending_readings: dict[str, dict] = {}
        self._forecast_kw: Optional[list[float]] = None
        self._forecast_ts: Optional[datetime] = None
        self._forecast_detail: Optional[dict] = None  # per-device forecast + unavoidable_kw (decider input)
        self._warnings: list[dict] = []
        self._active_commands: list[dict] = []
        self._recent_decisions: list[dict] = []
        self._escalations: dict[str, dict] = {}
        self._queued_decisions: list[dict] = []
        self._queued_commands: list[dict] = []
        self._pending_commands: dict[str, dict] = {}
        self._sent_commands: set[str] = set()
        self._command_meta: dict[str, dict] = {}
        self._active_meta: dict[str, dict] = {}
        self._protected: dict[str, datetime] = {}
        self._rejected: dict[str, datetime] = {}
        self._disabled: set[str] = set()
        self._cooldowns: dict[str, datetime] = {}
        self._warned_blocks: set[datetime] = set()
        self._ledger = Ledger()

    @classmethod
    def build_lanes(cls, config: Any, tariff: Any, catalog: Any, seed: int) -> dict[str, "Kitchen"]:
        """Both lanes sharing one id allocator (ENGINE.md section 0)."""
        ids = IdAllocator()
        return {lane: cls(config, tariff, catalog, lane, seed, ids=ids) for lane in LANES}

    @staticmethod
    def _build_roster(config: KitchenConfig, catalog: Mapping[str, TypeFacts]) -> dict[str, _Unit]:
        units: dict[str, _Unit] = {}
        for entry in config.equipment:
            facts = lookup(catalog, entry.type_id)
            limits = entry.limits.model_dump(mode="json")
            rules.validate_limits(entry.importance, limits, facts.category, facts.power_model)
            for n in range(1, entry.count + 1):
                device_id = f"{entry.type_id}_{n}"
                if device_id in units:
                    raise ValueError(f"duplicate device {device_id} (type {entry.type_id} listed twice)")
                units[device_id] = _Unit(device_id, n, facts, entry.importance, dict(limits))
        return {d: units[d] for d in sorted(units)}

    # ------------------------------------------------------------------------------------------------------------------
    # warm-up
    # ------------------------------------------------------------------------------------------------------------------
    def warm_up(self, history: Any) -> None:
        if self._stepped or self._warmed_up:
            raise RuntimeError("warm_up is called once per lane, before the first step")
        hist = WarmUpHistory.model_validate(_plain(history))
        end = hist.end
        per_block: dict[datetime, dict[str, float]] = {}
        for block in hist.blocks:
            if block.block_start + BLOCK > end:
                raise ValueError(f"warm-up block {block.block_start.isoformat()} ends after the start (no peeking)")
            if block_start_of(block.block_start) != block.block_start:
                raise ValueError(f"warm-up block {block.block_start.isoformat()} is not on a 15-min boundary")
            if block.device_id not in self._units:
                raise ValueError(f"warm-up block for unknown device {block.device_id!r}")
            devices = per_block.setdefault(block.block_start, {})
            if block.device_id in devices:
                raise ValueError(f"duplicate warm-up block {block.device_id} {block.block_start.isoformat()}")
            devices[block.device_id] = block.avg_kw

        current_month = self._tariff.local_month(end)
        for block_start in sorted(per_block):
            devices = {d: per_block[block_start][d] for d in sorted(per_block[block_start])}
            self._history.add(block_start, devices, sum(devices.values()))
            if hist.month_to_date is None and self._tariff.local_month(block_start) == current_month:
                for i in range(15):  # month to date: meter the current local month's blocks on the tariff
                    self._meter.meter_minute(block_start + i * MINUTE, devices)
        if hist.month_to_date is not None:
            self._meter.restore_month_to_date(hist.month_to_date, end)
        self._history.prune(end)
        self._now = end
        self._warmed_up = True

    # ------------------------------------------------------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------------------------------------------------------
    def step(self, minutes: int, hub_report: Any) -> dict:
        report = HubReport.model_validate(_plain(hub_report))
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
            raise ValueError(f"minutes must be a positive integer, got {minutes!r}")
        if report.lane != self.control:
            raise ValueError(f"HubReport lane {report.lane!r} sent to the {self.control!r} lane")
        ts = report.ts
        first_minute = ts - minutes * MINUTE
        if self._now is not None and first_minute < self._now:
            raise ValueError(f"step covers [{first_minute.isoformat()}, {ts.isoformat()}) but now is {self._now.isoformat()}")

        devices = self._apply_readings(report)
        device_kw = {d["device_id"]: d["power_kw"] for d in devices}
        for i in range(minutes):
            for closed in self._meter.meter_minute(first_minute + i * MINUTE, device_kw):
                self._history.add(closed.block_start, closed.device_avg_kw, closed.avg_kw)
        self._history.prune(ts)

        self._now = ts
        self._tick_id = report.tick_id
        self._stepped = True
        self._devices = {d["device_id"]: d for d in devices}
        self._total_kw = sum(device_kw[d] for d in sorted(device_kw))
        self._indoor_temp_c = self._read_indoor_temp(devices)
        self._consume_acks(report)
        reduced = {c["device_id"] for c in self._active_commands if c["action"] == "reduce"}
        self._ledger.observe(device_kw, minutes, reduced)

        warnings: list[dict] = []
        new_escalations: list[dict] = []
        forecast_kw: Optional[list[float]] = None
        replan = minutes > 1 or report.tick_id % DECISION_EVERY_TICKS == 0
        residual = self._forecast_detail
        if replan:
            fc = self._forecast(ts)
            target = self._meter_now()["target_kw"]
            if self.control == "with":
                for start, unavoidable in zip(fc["block_starts"], fc["unavoidable_kw"]):
                    if unavoidable > target + 1e-9 and start not in self._warned_blocks:
                        warnings.append({"code": "cap_unreachable", "message": "The peak target exceeds available control.",
                                         "data": {"unavoidable_kw": unavoidable, "peak_cap_kw": self.peak_cap_kw,
                                                  "target_kw": target}})
                        self._warned_blocks.add(start)
                result = plan(now=ts, forecast=fc, devices=self._planning_devices(), target=target,
                              tariff=self._tariff, operating_hours=self.config.operating_hours.model_dump(),
                              active=self._active_meta,
                              protected={**self._protected, **{c["device_id"]: ts + MINUTE for c in self._queued_commands}},
                              rejected=self._rejected,
                              cooldowns=self._cooldowns, peaks=self._meter.peaks_kw,
                              reason_code="stay_under_cap" if self.peak_mode == "cap" else "avoid_new_peak")
                for action in result["actions"]:
                    self._issue(**action)
                residual = result["forecast"]
            else:
                residual = fc
            forecast_kw = residual["total_kw"]
            self._forecast_kw, self._forecast_ts, self._forecast_detail = list(forecast_kw), ts, residual
        if self.control == "with":
            from .escalation import update
            escalation_fc = self._escalation_forecast() if replan and any(m.get("escalation") for m in self._active_meta.values()) else residual
            new_escalations = update(self, ts, escalation_fc, replan=replan)
            if replan:
                forecast_kw = copy.deepcopy(self._forecast_kw)
        self._warnings = warnings
        self._warned_blocks = {b for b in self._warned_blocks if b + BLOCK >= ts}
        new_decisions, self._queued_decisions = self._queued_decisions, []
        new_commands, self._queued_commands = self._queued_commands, []
        self._sent_commands.update(c["command_id"] for c in new_commands)

        state = {
            "lane": self.control,
            "ts": ts,
            "hub": report.model_dump(mode="json", exclude_unset=True),  # echo: only the fields the hub sent
            "meter": self._meter_now(),
            "customers_per_hour": report.customers_per_hour,
            "new_decisions": new_decisions,
            "new_commands": new_commands,
            "new_escalations": new_escalations,
            "warnings": warnings,
            "indoor_temp_c": self._indoor_temp_c,
            "forecast_kw": forecast_kw,
        }
        out = TickState.model_validate(state).model_dump(mode="json")
        out["hub"] = state["hub"]  # the dump re-adds unset optional fields as null; keep the echo as the hub sent it
        return out

    def _apply_readings(self, report: HubReport) -> list[dict]:
        """Devices in sorted id order, with any pending measured Reading applied (ENGINE.md section 10)."""
        devices = [d.model_dump(mode="json", exclude_unset=True) for d in report.devices]
        for d in devices:
            reading = self._pending_readings.get(d["device_id"])
            if reading is not None:
                d["power_kw"] = reading["power_kw"]
                d["power_pct"] = round(100 * reading["power_kw"] / d["rated_kw"])
                d["source"] = "measured"
            unit = self._units.get(d["device_id"])
            if unit is not None:
                d["importance"] = unit.importance  # the engine's rules are the truth of importance
        self._pending_readings = {}
        return sorted(devices, key=lambda d: d["device_id"])

    def _read_indoor_temp(self, devices: list[dict]) -> float:
        """The kitchen's one dining-room temperature, shared by every thermal (HVAC) unit's physical.indoor_temp_c."""
        for d in devices:
            unit = self._units.get(d["device_id"])
            temp = (d.get("physical") or {}).get("indoor_temp_c")
            if temp is not None and unit is not None and unit.facts.power_model == "thermal":
                return temp
        if self._indoor_temp_c is not None:
            return self._indoor_temp_c
        return DEFAULT_INDOOR_TEMP_C

    def _planning_devices(self) -> list[dict]:
        devices = []
        for device_id in sorted(self._devices):
            unit = self._units.get(device_id)
            if unit is None:
                continue
            d = copy.deepcopy(self._devices[device_id])
            d.update(power_model=unit.facts.power_model, category=unit.facts.category,
                     params=dict(unit.facts.params), limits=dict(unit.limits), disabled=device_id in self._disabled)
            devices.append(d)
        return devices

    def _forecast(self, ts: datetime, *, ignore_escalation: bool = False) -> dict:
        """Forecast from past hub reports, with acknowledged reductions and owed energy."""
        reductions = {}
        for did, meta in self._active_meta.items():
            if ignore_escalation and meta.get("escalation"):
                continue
            if meta["action"] == "reduce":
                reductions[did] = {"value_pct": meta["value"], "restore_at": meta["restore_at"],
                                   "owed_kwh": self._ledger.owed(did)}
        devices = self._planning_devices()
        if ignore_escalation:
            for d in devices:
                if self._active_meta.get(d["device_id"], {}).get("escalation"):
                    d["power_kw"] = self._ledger.expected_kw.get(d["device_id"], d["power_kw"])
        metered = self._meter.metered_device_kwh(block_start_of(ts))
        out = forecast_devices(now=ts, history=self._history.view(ts), tariff=self._tariff,
                               devices=devices, block0_metered_kwh=metered,
                               crowd_multiplier=self._context.crowd_multiplier(), reductions=reductions)
        out["_metered_kwh"] = dict(metered)
        out["_now"] = ts
        # Known jobs are finite cycles, unlike an idle device's expected-value history base.
        for d in devices:
            if d["importance"] != "deferrable":
                continue
            did = d["device_id"]
            meta = self._active_meta.get(did, {})
            if ignore_escalation and meta.get("escalation"):
                meta = {}
            if d["state"] in ("waiting", "running_job"):
                start = ts if d["state"] == "running_job" else max(ts, meta.get("release_at", ts))
                cycle = (d.get("physical") or {}).get("job_remaining_min")
                if cycle is None or cycle <= 0:
                    cycle = d["params"].get("cycle_min", 15)
                end = start + cycle * MINUTE
                for i, block in enumerate(out["block_starts"]):
                    overlap = max(0.0, (min(block + BLOCK, end) - max(block, start, ts)) / MINUTE)
                    kw = d["rated_kw"] * overlap / 15
                    if i == 0:
                        kw += metered.get(did, 0.0) * 4
                    previous = out["device_kw"][did][i]
                    out["device_kw"][did][i] = kw
                    if d["state"] == "running_job":
                        out["unavoidable_kw"][i] += kw - previous
                    elif self._tariff.minute_of_day(ts) + cycle >= rules.effective_deadline_min(
                            d["limits"]["must_finish_by"], self.config.operating_hours.close):
                        # A waiting job whose deadline no longer permits a hold must run now.
                        out["unavoidable_kw"][i] += kw - (metered.get(did, 0.0) * 4 if i == 0 else 0.0)
        totals(out)
        return out

    def _escalation_forecast(self) -> dict:
        """Residual in-rules plan without credit for an active rule-breaking fallback."""
        fc = self._forecast(self._now, ignore_escalation=True)
        active = {d: m for d, m in self._active_meta.items() if not m.get("escalation")}
        return plan(now=self._now, forecast=fc, devices=self._planning_devices(),
                    target=self._meter_now()["target_kw"], tariff=self._tariff,
                    operating_hours=self.config.operating_hours.model_dump(), active=active,
                    protected=self._protected, rejected=self._rejected, cooldowns=self._cooldowns,
                    peaks=self._meter.peaks_kw)["forecast"]

    def _meter_now(self) -> dict:
        if self._now is None:
            raise RuntimeError("no sim time yet: call warm_up or step first")
        target = target_kw(self.peak_mode, self.peak_cap_kw, self._history.view(self._now), self._tariff, self._now,
                           self._meter.month_peak_kw)
        meter = self._meter.reading(ts=self._now, total_kw=self._total_kw, peak_mode=self.peak_mode,
                                    peak_cap_kw=self.peak_cap_kw, target_kw=target)
        return Meter.model_validate(meter).model_dump(mode="json")

    # ------------------------------------------------------------------------------------------------------------------
    # owner settings
    # ------------------------------------------------------------------------------------------------------------------
    def set_importance(self, device_id: str, importance: str, limits: Any) -> dict:
        unit = self._unit(device_id)
        lim = rules.normalize_limits(importance, _plain(limits))
        rules.validate_limits(importance, lim, unit.facts.category, unit.facts.power_model)
        unit.importance = importance
        unit.limits = dict(lim)
        active = self._active_meta.get(device_id)
        if active is not None and active.get("issued_by") == "engine":
            if active["action"] == "reduce" and (importance != "flexible" or active["value"] < lim.get("min_power_pct", 100)):
                self._issue(device_id, "restore", None, "catch_up", issued_by="owner")
            elif active["action"] == "delay" and importance != "deferrable":
                self._issue(device_id, "delay", 0, "release_into_valley", issued_by="owner")
        return self._device_view(unit)

    def set_peak_cap(self, peak_mode: str, peak_cap_kw: Optional[float]) -> dict:
        rules.check_peak_cap(peak_mode, peak_cap_kw)
        self.peak_mode = peak_mode
        self.peak_cap_kw = None if peak_cap_kw is None else float(peak_cap_kw)
        return self._meter_now()

    def set_authority(self, authority: Any) -> None:
        self.authority = ClaudeAuthority.model_validate(_plain(authority)).model_dump(mode="json")

    def set_preferences(self, text: str) -> None:
        if not isinstance(text, str):
            raise RuleError("preferences must be text")
        self.preferences = text

    def set_context(self, context: Any) -> None:
        self._context.merge(context)

    def ingest_reading(self, reading: Any) -> dict:
        if self.control != "with":
            raise RuleError("measured readings feed the with lane only")
        r = Reading.model_validate(_plain(reading)).model_dump(mode="json")
        unit = self._unit(r["device_id"])
        self._pending_readings[unit.device_id] = r
        device = self._device_view(unit)
        device["power_kw"] = r["power_kw"]
        device["power_pct"] = round(100 * r["power_kw"] / device["rated_kw"])
        device["source"] = "measured"
        return Device.model_validate(device).model_dump(mode="json")

    def _unit(self, device_id: str) -> _Unit:
        try:
            return self._units[device_id]
        except KeyError:
            raise KeyError(f"unknown device {device_id!r}") from None

    def _device_view(self, unit: _Unit) -> dict:
        """Latest HubReport state of the device (roster default before the first report), engine importance."""
        device = copy.deepcopy(self._devices.get(unit.device_id))
        if device is None:
            device = {"device_id": unit.device_id, "type_id": unit.facts.type_id, "name": f"{unit.facts.name} {unit.n}",
                      "importance": unit.importance, "state": "off", "power_kw": 0.0, "rated_kw": unit.facts.rated_kw,
                      "power_pct": 0, "source": "simulated"}
        device["importance"] = unit.importance
        return Device.model_validate(device).model_dump(mode="json")

    def _reported_device(self, device_id: str) -> dict:
        unit = self._units.get(device_id)
        return self._device_view(unit) if unit is not None else copy.deepcopy(self._devices[device_id])

    # ------------------------------------------------------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------------------------------------------------------
    def open_escalations(self) -> list[dict]:
        return [Escalation.model_validate(e).model_dump(mode="json") for _, e in sorted(self._escalations.items())
                if e["status"] == "open"]

    def snapshot(self) -> dict:
        """Pure: no side effects, returns copies (ENGINE.md section 12)."""
        return {
            "tick_id": self._tick_id,
            "sim_ts": None if self._now is None else self._now.isoformat().replace("+00:00", "Z"),
            "lane": self.control,
            "control": self.control,
            "peak_mode": self.peak_mode,
            "config": self.config.model_dump(mode="json"),
            "meter": None if self._now is None else self._meter_now(),
            "forecast_kw": copy.deepcopy(self._forecast_kw),
            "forecast_ts": None if self._forecast_ts is None else self._forecast_ts.isoformat().replace("+00:00", "Z"),
            "devices": [self._reported_device(d) for d in sorted(self._devices)],
            "active_commands": copy.deepcopy(self._active_commands),
            "owed_kwh": {d: self._ledger.owed(d) for d, u in self._units.items() if u.importance == "flexible"},
            "open_escalations": self.open_escalations(),
            "warnings": copy.deepcopy(self._warnings),
            "recent_decisions": copy.deepcopy(self._recent_decisions),
            "context": self._context.current(),
            "id_counters": self.ids.counters(),
        }

    def forecast(self, horizon_min: int) -> list[float]:
        if horizon_min != FORECAST_HORIZON_MIN:
            raise ValueError(f"horizon_min is fixed at {FORECAST_HORIZON_MIN} in this build")
        # Before the first decision tick there is no forecast yet: an empty list (no recomputation here).
        return list(self._forecast_kw) if self._forecast_kw is not None else []

    # ------------------------------------------------------------------------------------------------------------------
    # later modules
    # ------------------------------------------------------------------------------------------------------------------
    def _check_action(self, device_id: str, action: str, value: Optional[int], *, owner: bool = False,
                      escalation: bool = False, at: Optional[datetime] = None) -> None:
        at = self._now if at is None else at
        unit = self._unit(device_id)
        if not owner:
            rules.check_engine_command(unit.importance, action)
            if device_id in self._disabled:
                raise RuleError("unknown_device: device disabled for this run")
            if self._protected.get(device_id, self._now) > self._now:
                raise RuleError("device is protected by an owner command")
        if action == "reduce":
            if owner:
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                    raise RuleError("reduce value must be an integer 0..100")
                if value < rules.power_floor_pct(unit.facts.category):
                    raise RuleError("reduce crosses the food-safety floor")
            else:
                rules.check_reduce(unit.importance, unit.limits, unit.facts.category, value, escalation=escalation)
        elif action == "delay":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RuleError("delay value must be an integer >= 0")
            if not owner and not escalation:
                first = self._active_meta.get(device_id, {}).get("first_applied", at)
                if self._tariff.local_date(at + value * MINUTE) != self._tariff.local_date(first):
                    raise RuleError("hold must finish on its service day")
                rules.check_hold(unit.importance, unit.limits, close=self.config.operating_hours.close,
                                 cycle_min=int(unit.facts.params.get("cycle_min", 0)),
                                 first_applied_min=self._tariff.minute_of_day(first),
                                 release_min=self._tariff.minute_of_day(at + value * MINUTE),
                                 open=self.config.operating_hours.open)
        elif action not in ("on", "off", "start", "restore"):
            raise RuleError(f"unknown action {action!r}")
        if self._devices.get(device_id, {}).get("state") == "running_job" and action in ("delay", "start"):
            raise RuleError("job_running")

    def _issue(self, device_id: str, action: str, value: Optional[int], reason_code: str,
               issued_by: str = "engine", escalation: bool = False, effect: Optional[dict] = None,
               restore_at: Optional[datetime] = None, release_at: Optional[datetime] = None) -> tuple[dict, dict]:
        if self._now is None:
            raise RuleError("no sim time yet")
        self._check_action(device_id, action, value, owner=issued_by == "owner", escalation=escalation)
        unit = self._unit(device_id)
        if effect is None:
            baseline = self._forecast_detail or self._forecast(self._now)
            projected = self._project_action(baseline, device_id, action, value, self._now,
                                             restore_at=restore_at, release_at=release_at)
            from .decider import effect as decision_effect
            effect = decision_effect(baseline, projected, self._tariff, self._meter.peaks_kw)
        decision = Decision.model_validate({"decision_id": self.ids.next("d"), "ts": self._now,
                    "device_id": device_id, "action": action, "value": value, "reason_code": reason_code,
                    "inside_rules": not escalation, "status": "executed", "effect": effect}).model_dump(mode="json")
        command = Command.model_validate({"command_id": self.ids.next("c"), "lane": self.control,
                    "ts": self._now, "device_id": device_id, "action": action, "value": value,
                    "decision_id": decision["decision_id"], "issued_by": issued_by}).model_dump(mode="json")
        old = self._active_meta.get(device_id, {})
        duration = unit.limits.get("max_reduce_min", 30)
        meta = dict(command, first_applied=old.get("first_applied", self._now),
                    restore_at=restore_at or old.get("restore_at", self._now + max(5, duration // 5 * 5) * MINUTE),
                    release_at=release_at or self._now + (value or 0) * MINUTE,
                    escalation=escalation)
        if action == "reduce":
            raw = self._forecast_detail or self._forecast(self._now)
            expected = max(raw["device_kw"].get(device_id, [self._devices.get(device_id, {}).get("power_kw", 0)]))
            self._ledger.reduce(device_id, expected)
            meta["expected_kw"] = self._ledger.expected_kw[device_id]
        self._command_meta[command["command_id"]] = meta
        self._pending_commands[command["command_id"]] = command
        self._queued_decisions.append(decision)
        self._queued_commands.append(command)
        self._recent_decisions.insert(0, copy.deepcopy(decision))
        del self._recent_decisions[20:]
        return decision, command

    def _consume_acks(self, report: HubReport) -> None:
        acks = {a.command_id: a for a in report.acks if a.lane == self.control}
        for cid in sorted(self._sent_commands, key=lambda c: int(c.rsplit("_", 1)[1])):
            command = self._pending_commands.pop(cid, None)
            meta = self._command_meta.pop(cid, None)
            self._sent_commands.discard(cid)
            if command is None or meta is None:
                continue
            ack = acks.get(cid)
            did = command["device_id"]
            if ack is None or not ack.ok:
                self._rejected[did] = block_start_of(report.ts)
                if ack is not None and ack.reason == "unknown_device":
                    self._disabled.add(did)
                if ack is not None and ack.reason == "job_running":
                    self._active_meta.pop(did, None)
                    self._active_commands = [c for c in self._active_commands if c["device_id"] != did]
                continue
            if command["action"] in ("reduce", "delay") and ack.applied_value is not None:
                command["value"] = meta["value"] = ack.applied_value
            previous = self._active_meta.pop(did, None)
            self._active_commands = [c for c in self._active_commands if c["device_id"] != did]
            if command["action"] in ("reduce", "delay", "off") and not (command["action"] == "delay" and command["value"] == 0):
                self._active_commands.append(command)
                self._active_meta[did] = meta
            if command["action"] in ("restore", "on") and previous and previous["action"] == "reduce":
                duration = self._units[did].limits.get("max_reduce_min", 30)
                self._cooldowns[did] = report.ts + duration * MINUTE
        # A hold expires in the hub itself; keep no stale active command after its release.
        for did, meta in list(self._active_meta.items()):
            if meta["action"] == "delay" and report.ts >= meta["release_at"]:
                del self._active_meta[did]
                self._active_commands = [c for c in self._active_commands if c["device_id"] != did]

    def owner_command(self, device_id: str, action: str, value: Optional[int]) -> dict:
        _, command = self._issue(device_id, action, value, "owner_override", issued_by="owner")
        self._protected[device_id] = self._now + 30 * MINUTE
        return copy.deepcopy(command)

    def undo(self, decision_id: str) -> dict:
        if self.control != "with":
            raise RuleError("undo is available on the with lane only")
        command = next((c for c in self._active_commands if c["decision_id"] == decision_id), None)
        decision = next((d for d in self._recent_decisions if d["decision_id"] == decision_id), None)
        if command is None or command["action"] not in ("reduce", "delay") or (decision and decision["status"] != "executed") or (command and self._active_meta.get(command["device_id"], {}).get("undone")):
            raise RuleError("decision is not an active, executed reduce or delay")
        did = command["device_id"]
        if command["action"] == "reduce":
            action, value = "restore", None
        elif self._devices.get(did, {}).get("state") == "waiting":
            action, value = "start", None
        else:
            action, value = "delay", 0
        revert = Command.model_validate({"command_id": self.ids.next("c"), "lane": self.control,
                    "ts": self._now, "device_id": did, "action": action, "value": value,
                    "decision_id": decision_id, "issued_by": "owner"}).model_dump(mode="json")
        self._pending_commands[revert["command_id"]] = revert
        self._command_meta[revert["command_id"]] = dict(revert, first_applied=self._now,
                    release_at=self._now, restore_at=self._now)
        self._queued_commands.append(revert)
        self._protected[did] = self._now + 30 * MINUTE
        if decision:
            decision["status"] = "undone"
            self._queued_decisions.append(copy.deepcopy(decision))
        else:
            # Active commands retain the decision id even after the 20-item display history rolls over.
            self._active_meta[did]["undone"] = True
        self._active_meta[did]["undone"] = True
        return copy.deepcopy(revert)

    def resolve_escalation(self, escalation_id: str, option_id: str, resolved_by: str,
                           rationale: Optional[str] = None) -> dict:
        from .escalation import resolve
        return resolve(self, escalation_id, option_id, resolved_by, rationale)

    def _project_action(self, forecast: dict, device_id: str, action: str, value: Optional[int], at: datetime,
                        *, restore_at: Optional[datetime] = None, release_at: Optional[datetime] = None) -> dict:
        """Pure action projection shared by marginal decisions, options and what_if."""
        unit = self._unit(device_id)
        projected = copy.deepcopy(forecast)
        if action == "reduce":
            projected = reduce_forecast(projected, device_id, unit.facts.rated_kw, value,
                                        restore_at or at + unit.limits.get("max_reduce_min", 30) * MINUTE, at)
        elif action in ("restore", "on"):
            expected = self._ledger.expected_kw.get(device_id, self._devices.get(device_id, {}).get("power_kw", 0))
            rates = projected["device_kw"].get(device_id, [])
            for i, start in enumerate(projected["block_starts"]):
                if start + BLOCK > at:
                    fraction = max(0.0, (start + BLOCK - max(start, at)) / MINUTE) / 15
                    metered = projected.get("_metered_kwh", {}).get(device_id, 0.0) * 4 if i == 0 else 0.0
                    # Preserve both metered minutes and the planned minutes before a future `at`.
                    remaining = max(0.0, (start + BLOCK - max(start, self._now)) / MINUTE) / 15
                    baseline = max(0.0, rates[i] - metered) / remaining if remaining else 0.0
                    rates[i] += max(0.0, expected - baseline) * fraction
            totals(projected)
        elif action == "off":
            rates = projected["device_kw"].get(device_id, [])
            for i, start in enumerate(projected["block_starts"]):
                if start + BLOCK > at:
                    fraction = max(0.0, (start + BLOCK - max(start, at)) / MINUTE) / 15
                    metered = projected.get("_metered_kwh", {}).get(device_id, 0.0) * 4 if i == 0 else 0.0
                    remaining = max(0.0, (start + BLOCK - max(start, self._now)) / MINUTE) / 15
                    baseline = max(0.0, rates[i] - metered)
                    rates[i] -= baseline * fraction / remaining if remaining else 0
            totals(projected)
        elif action == "delay" and value:
            if release_at is not None:
                value = max(0.0, (release_at - at) / MINUTE)
            rates = projected["device_kw"].get(device_id, [])
            held = 0.0
            for i, start in enumerate(projected["block_starts"]):
                overlap = max(0.0, (min(start + BLOCK, at + value * MINUTE) - max(start, at)) / MINUTE) / 15
                metered = projected.get("_metered_kwh", {}).get(device_id, 0.0) * 4 if i == 0 else 0.0
                remaining = max(0.0, (start + BLOCK - max(start, self._now)) / MINUTE) / 15
                baseline = max(0.0, rates[i] - metered) / remaining if remaining else 0.0
                shifted = baseline * overlap
                held += shifted * .25
                rates[i] -= shifted
                release_fraction = max(0.0, (start + BLOCK - max(start, at + value * MINUTE)) / MINUTE) / 15
                if release_fraction:
                    repaid = min(max(0.0, unit.facts.rated_kw - baseline) * .25 * release_fraction, held)
                    rates[i] += repaid * 4
                    held -= repaid
            totals(projected)
        return projected

    def _effect_for(self, forecast: dict, device_id: str, action: str, value: Optional[int], at: datetime) -> dict:
        return effect(forecast, self._project_action(forecast, device_id, action, value, at),
                      self._tariff, self._meter.peaks_kw)

    def what_if(self, device_id: str, action: str, value: Optional[int], at: Any) -> dict:
        if self._now is None:
            raise RuleError("no sim time yet")
        at = datetime.fromisoformat(at.replace("Z", "+00:00")) if isinstance(at, str) else at
        if not isinstance(at, datetime) or at.tzinfo is None or not self._now <= at < self._now + 120 * MINUTE:
            raise RuleError("what_if timestamp must be within [now, now + 120 min)")
        try:
            self._check_action(device_id, action, value, at=at)
        except KeyError:
            raise RuleError(f"unknown device {device_id!r}") from None
        return Effect.model_validate(self._effect_for(self._forecast(self._now), device_id, action, value, at)).model_dump(mode="json")
