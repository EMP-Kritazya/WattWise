"""Target (ENGINE.md section 4) and decider (section 5).

Pure deterministic routine planner; no I/O and no command ids.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
import copy
import math

from . import rules
from .tariff import MINUTE, BLOCK, hhmm_to_min, in_span

from .history import HistoryView
from .tariff import TariffView

SAME_WEEKDAYS = 4


def minimize_target_kw(view: HistoryView, tariff: TariffView, now: datetime, month_peak_kw: float) -> float:
    """Highest closed-block avg kW over the 4 most recent same-weekday local days before today (history, no peeking).
    Past days never change, so the value is fixed for the whole local day. No history for those days -> month peak so
    far (0 while nothing has closed this month: no reductions until a block closes)."""
    today = tariff.local_date(now)
    peak: Optional[float] = None
    for k in range(1, SAME_WEEKDAYS + 1):
        day = today - timedelta(days=7 * k)
        start = tariff.local_midnight_utc(day)
        end = tariff.local_midnight_utc(day + timedelta(days=1))
        for _, kw in view.total_blocks_between(start, end):
            peak = kw if peak is None else max(peak, kw)
    return month_peak_kw if peak is None else peak


def target_kw(peak_mode: str, peak_cap_kw: Optional[float], view: HistoryView, tariff: TariffView, now: datetime,
              month_peak_kw: float) -> float:
    if peak_mode == "cap":
        return float(peak_cap_kw)
    return minimize_target_kw(view, tariff, now, month_peak_kw)


def horizon_cost(forecast: dict, tariff: TariffView, peaks: Optional[dict] = None) -> float:
    """Energy plus incremental demand over paid month peaks (fixed charges cancel)."""
    peaks = peaks or {}
    starts, kw = forecast["block_starts"], forecast["total_kw"]
    energy = sum(v * sum(tariff.energy_price(t + k * MINUTE) for k in range(15)) / 60
                 for t, v in zip(starts, kw))
    demand = 0.0
    for month in sorted({tariff.local_month(t) for t in starts}):
        for c in tariff.applicable(int(month[-2:])):
            projected = max((v for t, v in zip(starts, kw)
                             if tariff.local_month(t) == month and tariff.counts(c, t)), default=0.0)
            paid = peaks.get(c.name, 0.0) if month == tariff.local_month(starts[0]) else 0.0
            demand += c.usd_per_kw * max(0.0, projected - paid)
    return energy + demand


def totals(forecast: dict) -> None:
    n = len(forecast["block_starts"])
    forecast["total_kw"] = [sum(v[i] for v in forecast["device_kw"].values()) for i in range(n)]


def effect(before: dict, after: dict, tariff: TariffView, peaks: Optional[dict] = None) -> dict:
    return {"peak_before_kw": max(before["total_kw"], default=0.0),
            "peak_after_kw": max(after["total_kw"], default=0.0),
            "saving_usd": horizon_cost(before, tariff, peaks) - horizon_cost(after, tariff, peaks)}


def reduce_forecast(forecast: dict, did: str, rated: float, value: int, until: datetime,
                    now: datetime) -> dict:
    """Cap future energy only; meter history in block zero cannot be undone. Repay within rated room."""
    out = copy.deepcopy(forecast)
    owed = 0.0
    rates = out["device_kw"][did]
    for i, start in enumerate(out["block_starts"]):
        if start >= until:
            continue
        duration = max(0.0, (min(start + BLOCK, until) - max(start, now)) / MINUTE)
        cap = value / 100 * rated
        # The forecast already contains metered energy in block zero. Only the remaining fraction is controllable.
        fraction = duration / 15
        metered = forecast.get("_metered_kwh", {}).get(did, 0.0) * 4 if i == 0 else 0.0
        baseline_now = forecast.get("_now", now)
        remaining = max(0.0, (start + BLOCK - max(start, baseline_now)) / MINUTE) / 15
        controllable = max(0.0, (rates[i] - metered) / remaining) if remaining else 0.0
        new = rates[i] - max(0.0, controllable - cap) * fraction
        owed += (rates[i] - new) * .25
        rates[i] = new
    for i, start in enumerate(out["block_starts"]):
        if start < until:
            continue
        catch_up = min(max(0.0, rated - rates[i]) * .25, owed)
        rates[i] += catch_up * 4
        owed -= catch_up
    # Future energy that cannot fit the horizon remains owed, never silently counted as saved energy.
    out["unplaced_kwh"] = out.get("unplaced_kwh", 0.0) + owed
    totals(out)
    return out


def plan(*, now: datetime, forecast: dict, devices: list[dict], target: float, tariff: TariffView,
         operating_hours: dict, active: Optional[dict] = None, protected: Optional[dict] = None,
         rejected: Optional[dict] = None, cooldowns: Optional[dict] = None,
         peaks: Optional[dict] = None, reason_code: str = "stay_under_cap") -> dict:
    """Desired-state replan. Returns actions with marginal effects and its residual forecast.

    Only ids present in `devices` may be controlled. `active` entries contain action/value plus
    first_applied/restore_at/release_at. Unknown forecast ids contribute load but cannot be commanded.
    """
    current = copy.deepcopy(forecast)
    initial = copy.deepcopy(forecast)
    active, protected, rejected, cooldowns = active or {}, protected or {}, rejected or {}, cooldowns or {}
    actions: list[dict] = []
    starts = current["block_starts"]
    n = len(starts)
    minute = tariff.minute_of_day(now)
    opened, close = hhmm_to_min(operating_hours["open"]), hhmm_to_min(operating_hours["close"])
    is_open = in_span(minute, opened, close)
    by_id = {d["device_id"]: d for d in devices}
    changed: set[str] = set()

    def can_move(did: str) -> bool:
        return (did not in changed and protected.get(did, now) <= now
                and rejected.get(did) != starts[0] and not by_id[did].get("disabled", False))

    def add(did: str, action: str, value: Optional[int], projected: dict, reason: str,
            **metadata) -> None:
        nonlocal current
        actions.append({"device_id": did, "action": action, "value": value, "reason_code": reason,
                        "effect": effect(current, projected, tariff, peaks), **metadata})
        current = projected
        changed.add(did)

    # Restore at the last safe decision tick, even if the target remains unreachable.
    for did, command in sorted(active.items()):
        if did not in by_id or not can_move(did) or command.get("issued_by") == "owner":
            continue
        if command["action"] == "reduce":
            until = command.get("restore_at", now + BLOCK)
            restored = copy.deepcopy(current)
            expected = command.get("expected_kw")
            if expected is not None:
                rates = restored["device_kw"].get(did, [])
                for i, start in enumerate(starts):
                    if start >= until:
                        continue
                    fraction = max(0.0, (min(start + BLOCK, until) - max(start, now)) / MINUTE) / 15
                    rates[i] += max(0.0, expected - command["value"] / 100 * by_id[did]["rated_kw"]) * fraction
                totals(restored)
            no_longer_needed = (expected is not None and all(v <= target + 1e-9 for v in restored["total_kw"]))
            if now >= until or by_id[did]["importance"] != "flexible" or no_longer_needed:
                add(did, "restore", None, restored, "catch_up")
        elif command["action"] == "delay" and by_id[did].get("state") == "waiting":
            released = copy.deepcopy(current)
            remaining_kwh = sum(released["device_kw"][did]) * .25 - released.get("_metered_kwh", {}).get(did, 0)
            rates = [0.0] * n
            for i, start in enumerate(starts):
                capacity = by_id[did]["rated_kw"] * max(0.0, (start + BLOCK - max(start, now)) / MINUTE) / 60
                energy = min(capacity, remaining_kwh)
                rates[i] = energy * 4
                remaining_kwh -= energy
            rates[0] += released.get("_metered_kwh", {}).get(did, 0) * 4
            released["device_kw"][did] = rates
            totals(released)
            if remaining_kwh <= 1e-9 and all(v <= target + 1e-9 for v in released["total_kw"]):
                add(did, "start", None, released, "release_into_valley")

    if not is_open or target <= 0:
        return {"actions": actions, "forecast": current,
                "saving_usd": horizon_cost(initial, tariff, peaks) - horizon_cost(current, tariff, peaks)}

    for block in range(n):
        block_target = max(target, current.get("unavoidable_kw", [0.0] * n)[block])
        if current["total_kw"][block] <= block_target + 1e-9:
            continue
        # Move the entire contiguous job, preserving its kWh. Earliest feasible valley wins.
        for did, d in sorted(by_id.items()):
            if d["importance"] != "deferrable" or d.get("state") == "running_job" or not can_move(did):
                continue
            if did not in current["device_kw"] or current["device_kw"][did][block] <= 0:
                continue
            old = current["device_kw"][did]
            first = block
            while first > 0 and old[first - 1] > 0:
                first -= 1
            cycle = int(d.get("params", {}).get("cycle_min", 15))
            end = min(n, first + max(1, math.ceil(cycle / 15)))
            while end > first + 1 and old[end - 1] <= 0:
                end -= 1
            job = list(old[first:end])
            past_kw = current.get("_metered_kwh", {}).get(did, 0.0) * 4 if first == 0 else 0.0
            if first == 0:
                job[0] = max(0.0, job[0] - past_kw)
            cycle = int(d.get("params", {}).get("cycle_min", len(job) * 15))
            command = active.get(did, {})
            applied = command.get("first_applied", now)
            for dest in range(end, n - len(job) + 1):
                release = starts[dest]
                try:
                    rules.check_hold(d["importance"], d["limits"], close=operating_hours["close"],
                                     cycle_min=cycle, first_applied_min=tariff.minute_of_day(applied),
                                     release_min=tariff.minute_of_day(release), open=operating_hours["open"])
                except rules.RuleError:
                    continue
                if tariff.local_date(release) != tariff.local_date(applied):
                    continue
                projected = copy.deepcopy(current)
                rates = projected["device_kw"][did]
                for i in range(first, end):
                    rates[i] = past_kw if i == 0 else 0.0
                for j, kw in enumerate(job):
                    rates[dest + j] += kw
                totals(projected)
                if any(rates[dest+j] > d["rated_kw"] + 1e-9 for j in range(len(job))):
                    continue
                if any(projected["total_kw"][dest+j] > target + 1e-9 for j in range(len(job))):
                    continue
                delay = max(0, math.ceil((release - now) / MINUTE))
                if command.get("action") == "delay" and command.get("release_at") == release:
                    break
                add(did, "delay", delay, projected, reason_code, release_at=release)
                break
            if current["total_kw"][block] <= block_target + 1e-9:
                break

        # Largest reducible device first. One desired cap per device for this replan.
        candidates = []
        for did, d in by_id.items():
            if d["importance"] != "flexible" or not can_move(did) or cooldowns.get(did, now) > now:
                continue
            duration = d["limits"]["max_reduce_min"]
            if close - minute <= duration or duration < 5:
                continue
            command = active.get(did, {})
            until = command.get("restore_at", now + (duration // 5) * 5 * MINUTE)
            if starts[block] >= until:
                continue
            floor = max(d["limits"]["min_power_pct"], rules.power_floor_pct(d.get("category", "")))
            kw = current["device_kw"].get(did, [0.0] * n)[block]
            reducible = max(0.0, kw - floor / 100 * d["rated_kw"])
            candidates.append((-reducible, did, floor, until))
        for negative, did, floor, until in sorted(candidates):
            if negative >= 0:
                continue
            d = by_id[did]
            excess = current["total_kw"][block] - block_target
            kw = current["device_kw"][did][block]
            fraction = min(15.0, max(0.0, (min(starts[block]+BLOCK, until)-max(starts[block],now))/MINUTE)) / 15
            if fraction <= 0:
                continue
            metered = current.get("_metered_kwh", {}).get(did, 0.0) * 4 if block == 0 else 0.0
            remaining = max(0.0, (starts[block]+BLOCK-max(starts[block],now))/MINUTE) / 15
            controllable = max(0.0, (kw-metered)/remaining) if remaining else 0.0
            value = max(floor, min(100, math.ceil((controllable - excess / fraction) / d["rated_kw"] * 100 - 1e-10)))
            command = active.get(did, {})
            if command.get("action") == "reduce" and command.get("value") == value:
                continue
            projected = reduce_forecast(current, did, d["rated_kw"], value, until, now)
            if projected["total_kw"][block] >= current["total_kw"][block] - 1e-9:
                continue
            add(did, "reduce", value, projected, reason_code, restore_at=until)
            if current["total_kw"][block] <= block_target + 1e-9:
                break
    return {"actions": actions, "forecast": current,
            "saving_usd": horizon_cost(initial, tariff, peaks) - horizon_cost(current, tariff, peaks)}
