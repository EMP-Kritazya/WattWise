"""OpenEI URDB rate record -> the CONTRACTS.md section 1 Tariff shape (`label: "urdb"`), values unchanged (golden rule 6).

Conversion rules (CONTRACTS.md "Seasons, days and windows"; GAPS 22-23):
- Months with the same hourly schedule row (and the same day type) form one group; groups are ordered by their first month.
  When a month's weekday and weekend rows are equal the entries carry `days: "all"`, else `"weekdays"` / `"weekends"`.
- **Energy:** each group's 24-hour row is cut into runs of one period, starting with the run that holds 00:00 (a run that spans
  midnight becomes one wrapping entry, e.g. 21:00-16:00). One entry per run. Identical entries (same name, start, end, days)
  of several groups are merged into one with the union of months, kept at the position of the **last** group that has it.
- **Demand (TOU):** per group, every period with a non-zero rate becomes one charge whose `windows` are all its runs that day;
  identical charges of several groups merge (union of months, last position). URDB periods with rate 0 are omitted (no charge).
- **Demand (flat / max):** `flatdemandstructure` + `flatdemandmonths`; when every tier has the same rate it is one charge
  `max_demand` for every month (`months: null`), otherwise one charge per tier with its months. Listed first.
- **Fixed:** `fixedchargefirstmeter` with `fixedchargeunits` `$/day` or `$/month` -> one `customer_charge`.
- Entry names: URDB periods are unnamed, so a known rate carries a name table (`KNOWN`); unknown rates use `period_<i>`.

Tiered energy, demand ratchets, Peak Day Pricing and power-factor charges are not modelled (documented exclusions).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from contracts import Tariff

REPO_ROOT = Path(__file__).resolve().parents[2]
TARIFF_DIR = REPO_ROOT / "dataset" / "tariffs"
B19_FILE = TARIFF_DIR / "pge_b19_secondary_voluntary_urdb_69de8cdb02f684104e01267d.json"

KNOWN: dict[str, dict[str, Any]] = {
    "69de8cdb02f684104e01267d": {
        "tariff_id": "pge_b19_secondary_voluntary",
        "name": "PG&E B-19 Medium General Demand TOU (Secondary) Voluntary",
        "energy_names": {
            0: "super_off_peak_spring",
            1: "off_peak_winter",
            2: "peak_winter",
            3: "off_peak_summer",
            4: "part_peak_summer",
            5: "peak_summer",
        },
        "demand_names": {1: "peak_demand_winter", 2: "part_peak_demand_summer", 3: "peak_demand_summer"},
    },
}
TIMEZONE = "America/Los_Angeles"  # every PG&E rate


def _hh(hour: int) -> str:
    return f"{hour:02d}:00"


def _runs(row: list[int]) -> list[tuple[int, int, int]]:
    """24 hourly period indexes -> [(period, start_h, end_h)] starting with the run holding 00:00; a run crossing midnight
    is one wrapping run (start_h > end_h). A single period all day -> [(p, 0, 24)]."""
    if len(row) != 24:
        raise ValueError(f"URDB schedule row has {len(row)} hours, expected 24")
    runs: list[list[int]] = []
    for h, p in enumerate(row):
        if runs and runs[-1][0] == p:
            runs[-1][2] = h + 1
        else:
            runs.append([p, h, h + 1])
    if len(runs) == 1:
        return [(runs[0][0], 0, 24)]
    if runs[0][0] == runs[-1][0]:  # wraps midnight
        last = runs.pop()
        runs[0][1] = last[1]
    return [tuple(r) for r in runs]  # type: ignore[misc]


def _groups(weekday: list[list[int]], weekend: list[list[int]]) -> list[tuple[list[int], str, list[int]]]:
    """[(months 1-12, days, row)] ordered by first month (then weekdays before weekends)."""
    keyed: dict[tuple[tuple[int, ...], str], list[int]] = {}
    for m in range(12):
        wd, we = weekday[m], weekend[m]
        pairs = [(wd, "all")] if wd == we else [(wd, "weekdays"), (we, "weekends")]
        for row, days in pairs:
            keyed.setdefault((tuple(row), days), []).append(m + 1)
    out = [(months, days, list(row)) for (row, days), months in keyed.items()]
    order = {"all": 0, "weekdays": 0, "weekends": 1}
    return sorted(out, key=lambda g: (g[0][0], order[g[1]]))


def _merge_last(entries: dict[Any, dict], key: Any, months: list[int], make) -> None:
    """Insert or merge an entry keyed by `key`, moving it to the end (= the position of the last group that has it)."""
    if key in entries:
        entry = entries.pop(key)
        entry["months"] = sorted(set(entry["months"]) | set(months))
    else:
        entry = make()
        entry["months"] = list(months)
    entries[key] = entry


def _months_or_null(months: list[int]) -> Optional[list[int]]:
    return None if sorted(months) == list(range(1, 13)) else sorted(months)


def convert_urdb(record: dict) -> dict:
    """One URDB `items[]` record -> Tariff dict (JSON-ready, validates as `contracts.Tariff`)."""
    label = record["label"]
    known = KNOWN.get(label, {})
    energy_names = known.get("energy_names", {})
    demand_names = known.get("demand_names", {})

    # energy -------------------------------------------------------------------------------------------------------------
    rates = record["energyratestructure"]
    for tiers in rates:
        if len(tiers) != 1:
            raise ValueError(f"URDB {label}: tiered energy rates are not modelled")
    energy: dict[Any, dict] = {}
    for months, days, row in _groups(record["energyweekdayschedule"], record["energyweekendschedule"]):
        for p, a, b in _runs(row):
            name = energy_names.get(p, f"period_{p}")
            price = rates[p][0]["rate"]
            _merge_last(energy, (name, a, b, days, price), months, lambda: {
                "name": name, "start": _hh(a), "end": _hh(b), "usd_per_kwh": price, "months": None, "days": days})
    energy_list = []
    for e in energy.values():
        e["months"] = _months_or_null(e["months"])
        energy_list.append({k: e[k] for k in ("name", "start", "end", "usd_per_kwh", "months", "days")})

    # demand: flat (max) first, then TOU -----------------------------------------------------------------------------------
    demand_list: list[dict] = []
    flat = record.get("flatdemandstructure") or []
    if flat:
        flat_rates = []
        for tiers in flat:
            if len(tiers) != 1:
                raise ValueError(f"URDB {label}: tiered flat demand is not modelled")
            flat_rates.append(tiers[0]["rate"])
        flat_months = record.get("flatdemandmonths") or [0] * 12
        if len(set(flat_rates)) == 1:
            if flat_rates[0] > 0:
                demand_list.append({"name": "max_demand", "windows": None, "months": None, "days": "all",
                                    "usd_per_kw": flat_rates[0]})
        else:
            for i, rate in enumerate(flat_rates):
                months = [m + 1 for m in range(12) if flat_months[m] == i]
                if rate > 0 and months:
                    demand_list.append({"name": f"max_demand_{i}", "windows": None, "months": _months_or_null(months),
                                        "days": "all", "usd_per_kw": rate})
    tou = record.get("demandratestructure") or []
    if tou:
        tou_rates = []
        for tiers in tou:
            if len(tiers) != 1:
                raise ValueError(f"URDB {label}: tiered TOU demand is not modelled")
            tou_rates.append(tiers[0]["rate"])
        charges: dict[Any, dict] = {}
        for months, days, row in _groups(record["demandweekdayschedule"], record["demandweekendschedule"]):
            runs = _runs(row)
            for p, a, b in runs:
                if tou_rates[p] == 0:
                    continue
                windows = tuple((x, y) for q, x, y in runs if q == p)
                name = demand_names.get(p, f"demand_period_{p}")
                _merge_last(charges, (name, windows, days, tou_rates[p]), months, lambda: {
                    "name": name, "windows": [{"start": _hh(x), "end": _hh(y)} for x, y in windows], "months": None,
                    "days": days, "usd_per_kw": tou_rates[p]})
        for c in charges.values():
            c["months"] = _months_or_null(c["months"])
            demand_list.append({k: c[k] for k in ("name", "windows", "months", "days", "usd_per_kw")})

    # fixed ----------------------------------------------------------------------------------------------------------------
    fixed = []
    amount = record.get("fixedchargefirstmeter")
    if amount:
        units = record.get("fixedchargeunits")
        per = {"$/day": "day", "$/month": "month"}.get(units)
        if per is None:
            raise ValueError(f"URDB {label}: fixed charge unit {units!r} not modelled")
        fixed.append({"name": "customer_charge", "usd": amount, "per": per})

    tariff = {
        "tariff_id": known.get("tariff_id", f"urdb_{label}"),
        "name": known.get("name", record["name"]),
        "label": "urdb",
        "currency": "USD",
        "timezone": TIMEZONE,
        "energy": energy_list,
        "demand": demand_list,
        "fixed_charges": fixed,
    }
    Tariff.model_validate(tariff)  # exactly one energy period per local minute, etc.
    return tariff


def load_urdb_tariff(path: Path = B19_FILE) -> dict:
    """Read a saved URDB API response (`{"items": [record]}`) and convert it. Raises FileNotFoundError if absent."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"URDB file not found: {path} (dataset/ is gitignored)")
    doc = json.loads(path.read_text())
    items = doc["items"] if isinstance(doc, dict) and "items" in doc else [doc]
    if len(items) != 1:
        raise ValueError(f"{path}: expected one URDB record, found {len(items)}")
    return convert_urdb(items[0])
