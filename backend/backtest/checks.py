"""Backtest checks (DATA_AND_PROOF.md "Checks"): run after a backtest, before any number may be shown.

Per-month checks live in each BacktestResult (`baseline_matches_raw`, `energy_conserved`, `rule_violations`, computed by
`engine.run_backtest`). This module adds the run-level ones: month mark = last point, year to date, zero flexibility saves 0,
no-peeking guard never fired, deterministic rerun byte-identical. Passing every check is necessary, not sufficient:
`backtest-auditor` must still return CLEARED before a savings number leaves the backtest.
"""
from __future__ import annotations

import json
from typing import Optional, Sequence

from engine import run_backtest


def month_marks_equal_last_points(events: Sequence[dict]) -> bool:
    last: dict[str, dict] = {}
    ok = True
    for e in events:
        if e["type"] == "backtest_point":
            last[e["data"]["month"]] = e["data"]
        elif e["type"] == "backtest_month":
            r = e["data"]
            p = last.get(r["month"])
            ok &= p is not None and p["saved_month_to_date_usd"] == r["saved_usd"] \
                and p["saved_vs_timer_month_to_date_usd"] == r["saved_vs_timer_usd"] \
                and all(p["cost_to_date_usd"][k] == r["policies"][k]["total_usd"] for k in ("without", "timer", "with"))
    return bool(ok)


def year_to_date_consistent(events: Sequence[dict]) -> bool:
    before = 0.0
    for e in events:
        if e["type"] == "backtest_point":
            d = e["data"]
            if abs(d["saved_year_to_date_usd"] - round(before + d["saved_month_to_date_usd"], 2)) > 0.005:
                return False
        elif e["type"] == "backtest_month":
            before = round(before + e["data"]["saved_usd"], 2)
    return True


def deterministic(inputs: dict, months: Sequence[str], assumptions_id: str, first_events: Sequence[dict]) -> bool:
    again: list[dict] = []
    run_backtest(inputs, months, assumptions_id, again.append)
    return json.dumps(list(first_events), sort_keys=True) == json.dumps(again, sort_keys=True)


def zero_flex_saves_zero(inputs: dict, months: Sequence[str]) -> tuple[bool, str]:
    """The same series with every device always_on (`flex_scale` 0, id `zero_flex`): every month must save exactly $0.00."""
    zero = dict(inputs, assumptions=dict(inputs["assumptions"], assumptions_id="zero_flex", flex_scale=0.0))
    res = run_backtest(zero, months, "zero_flex")
    bad = [r["month"] for r in res if r["saved_usd"] != 0.0 or r["saved_vs_timer_usd"] != 0.0]
    return (not bad, "all months $0.00" if not bad else f"non-zero in {bad}")


def check_table(results: Sequence[dict], events: Sequence[dict], *, deterministic_ok: Optional[bool],
                zero_flex: Optional[tuple[bool, str]], peek_errors: int) -> list[tuple[str, str, str, bool]]:
    """Rows (check, expected, result, pass) for the CLI and the final report."""
    rows = []
    base = [r["month"] for r in results if not r["checks"]["baseline_matches_raw"]]
    rows.append(("without bill vs raw-data bill", "equal to the cent", "all months" if not base else f"differs: {base}", not base))
    energy = [r["month"] for r in results if not r["checks"]["energy_conserved"]]
    rows.append(("daily energy, every policy", "equal to the data (1e-6 kWh)", "all days" if not energy else f"off: {energy}",
                 not energy))
    viol = sum(r["checks"]["rule_violations"] for r in results)
    rows.append(("rule violations (timer + with)", "0", str(viol), viol == 0))
    if zero_flex is not None:
        rows.append(("zero-flexibility run", "saves $0.00", zero_flex[1], zero_flex[0]))
    rows.append(("no-peeking guard", "never triggered", f"{peek_errors} PeekError", peek_errors == 0))
    ok = month_marks_equal_last_points(events)
    rows.append(("month mark = last point of the month", "equal to the cent", "yes" if ok else "no", ok))
    ok = year_to_date_consistent(events)
    rows.append(("year to date = sum of marks + month to date", "equal", "yes" if ok else "no", ok))
    if deterministic_ok is not None:
        rows.append(("deterministic rerun", "byte-identical events", "yes" if deterministic_ok else "no", deterministic_ok))
    return rows
