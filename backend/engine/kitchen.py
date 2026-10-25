"""Kitchen facade (CONTRACTS.md section 3; ENGINE.md sections 0, 7, 10, 12).

One Kitchen per lane. Plain objects in (dicts or contract models), JSON-ready dicts out. No I/O, no wall clock:
time comes only from HubReport `ts` and WarmUpHistory `end`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional

from contracts import (
    ClaudeAuthority,
    Device,
    EquipmentType,
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
from .decider import target_kw
from .forecaster import forecast_devices
from .history import BlockHistory
from .ids import IdAllocator
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
        # STUB: executor (ENGINE.md section 7) not built; the engine has issued no Commands yet, so acks are not read.

        warnings: list[dict] = []
        new_decisions: list[dict] = []
        new_commands: list[dict] = []
        new_escalations: list[dict] = []
        forecast_kw: Optional[list[float]] = None
        if minutes > 1 or report.tick_id % DECISION_EVERY_TICKS == 0:  # replay: every step; live: tick_id % 5 == 0
            fc = self._forecast(ts)
            forecast_kw = fc["total_kw"]
            self._forecast_kw, self._forecast_ts, self._forecast_detail = forecast_kw, ts, fc
            # STUB: target warnings / decider / escalation (ENGINE.md sections 4-6) not built yet:
            # decision ticks issue no decisions, commands, escalations or cap_unreachable warnings.
        self._warnings = warnings

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

    def _forecast(self, ts: datetime) -> dict:
        """ENGINE.md section 3 on the latest HubReport, closed history only. Context is the one merged before this step."""
        devices = []
        for device_id in sorted(self._devices):
            d = dict(self._devices[device_id])
            unit = self._units.get(device_id)
            d["power_model"] = unit.facts.power_model if unit is not None else None
            d["limits"] = dict(unit.limits) if unit is not None else {}
            devices.append(d)
        # STUB: reductions (active reduce commands + owed energy) come with the decider / ledger (ENGINE.md sections 5, 9).
        return forecast_devices(now=ts, history=self._history.view(ts), tariff=self._tariff, devices=devices,
                                block0_metered_kwh=self._meter.metered_device_kwh(block_start_of(ts)),
                                crowd_multiplier=self._context.crowd_multiplier(), reductions=None)

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
        # STUB: active commands on a device whose importance changed are handled by the decider (not built yet).
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
        return [copy.deepcopy(e) for _, e in sorted(self._escalations.items())
                if e["status"] in ("open", "awaiting_owner")]

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
            # STUB: ledger (ENGINE.md section 9) not built; no reduction has run, so every flexible device owes 0 kWh.
            "owed_kwh": {d: 0.0 for d, u in self._units.items() if u.importance == "flexible"},
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
    def owner_command(self, device_id: str, action: str, value: Optional[int]) -> dict:
        # STUB: ENGINE.md section 7 owner commands.
        raise NotImplementedError("STUB: Kitchen.owner_command (ENGINE.md section 7)")

    def undo(self, decision_id: str) -> dict:
        # STUB: ENGINE.md section 7 undo.
        raise NotImplementedError("STUB: Kitchen.undo (ENGINE.md section 7)")

    def resolve_escalation(self, escalation_id: str, option_id: str, resolved_by: str,
                           rationale: Optional[str] = None) -> dict:
        # STUB: ENGINE.md section 6 resolve.
        raise NotImplementedError("STUB: Kitchen.resolve_escalation (ENGINE.md section 6)")

    def what_if(self, device_id: str, action: str, value: Optional[int], at: Any) -> dict:
        # STUB: ENGINE.md section 13 what_if.
        raise NotImplementedError("STUB: Kitchen.what_if (ENGINE.md section 13)")
