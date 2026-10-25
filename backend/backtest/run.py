"""CLI: run the backtest at full speed and write the DEMO_MODE cache (golden rule 10). Not committed (`data/` is gitignored).

    cd backend && .venv/bin/python -m backtest.run --months all --assumptions base --out ../data/backtest_cache/base.json

`--months`: `all` (every replay-calendar month with scored days: 2026-01 .. 2026-12), a comma list, or `2026-03..2026-08`.
The cache holds the exact `on_progress` events in order (what `/api/backtest/run` replays, paced, in DEMO_MODE), the
BacktestResults, the check table and run diagnostics. `audited` is false: no number in it is shown as a saving until
`backtest-auditor` returns CLEARED. Exit code 2 when the loader refuses the data (e.g. a device above rated_kw).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from backtest import checks
from backtest.assumptions import REPO_ROOT
from data.backtest_inputs import load_backtest_inputs, replay_months
from data.recipe import RatedKwExceeded
from engine.replay import run_backtest_with_diagnostics

DEFAULT_DIR = REPO_ROOT / "data" / "backtest_cache"


def parse_months(spec: str) -> list[str]:
    if spec == "all":
        return replay_months()
    if ".." in spec:
        a, b = spec.split("..")
        out, (y, m) = [], (int(a[:4]), int(a[5:]))
        while f"{y:04d}-{m:02d}" <= b:
            out.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    return [s.strip() for s in spec.split(",") if s.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backtest.run", description=__doc__.splitlines()[0])
    ap.add_argument("--months", default="all")
    ap.add_argument("--assumptions", default="base")
    ap.add_argument("--tariff", default="pge_b19", choices=["pge_b19", "demo"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-slow-checks", action="store_true", help="skip the rerun and zero-flex checks")
    a = ap.parse_args(argv)
    months = parse_months(a.months)
    out = Path(a.out) if a.out else DEFAULT_DIR / f"{a.assumptions}_{a.tariff}.json"

    t0 = time.monotonic()
    try:
        inputs = load_backtest_inputs(months, a.assumptions, tariff=a.tariff)
    except RatedKwExceeded as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    events: list[dict] = []
    results, diag = run_backtest_with_diagnostics(inputs, months, a.assumptions, events.append)
    t_run = time.monotonic() - t0

    det = zero = None
    if not a.skip_slow_checks:
        det = checks.deterministic(inputs, months, a.assumptions, events)
        zero = checks.zero_flex_saves_zero(inputs, months)
    table = checks.check_table(results, events, deterministic_ok=det, zero_flex=zero, peek_errors=diag.peek_errors)

    tariff = inputs["tariff"]
    cache = {
        "kind": "wattwise_backtest_cache", "version": 1, "audited": False,
        "note": "Not cleared by backtest-auditor: no number here may be shown as a saving yet.",
        "dataset": results[0]["dataset"] if results else None,
        "dataset_id": inputs["series"]["dataset_id"], "series_label": inputs["series"]["label"],
        "tariff": {"tariff_id": tariff["tariff_id"], "name": tariff["name"], "label": tariff["label"]},
        "assumptions_id": a.assumptions, "months": months,
        "events": events, "results": results,
        "checks": [{"check": c, "expected": e, "result": r, "pass": p} for c, e, r, p in table],
        "diagnostics": {"timer_schedules": diag.timer_schedules, "over_rated_blocks": diag.over_rated_blocks,
                        "violation_log": diag.violation_log[:50], "commands_issued": diag.commands_issued,
                        "kitchen_meter_max_gap_usd": diag.kitchen_meter_max_gap_usd, "scored_days": diag.scored_days,
                        "run_seconds": round(t_run, 1)},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cache, indent=1, sort_keys=False) + "\n", encoding="utf-8")

    print(f"{cache['dataset']} · {tariff['name']} ({tariff['label']}) · assumptions {a.assumptions} · {t_run:.1f} s")
    print(f"{'month':8} {'days':>4} {'without':>10} {'timer':>10} {'with':>10} {'saved':>8} {'vs timer':>9}  partial")
    for r in results:
        p = r["policies"]
        print(f"{r['month']:8} {diag.scored_days.get(r['month'], 0):>4} {p['without']['total_usd']:>10.2f} "
              f"{p['timer']['total_usd']:>10.2f} {p['with']['total_usd']:>10.2f} {r['saved_usd']:>8.2f} "
              f"{r['saved_vs_timer_usd']:>9.2f}  {r['partial']}")
    for c, e, r, ok in table:
        print(f"[{'PASS' if ok else 'FAIL'}] {c}: expected {e}; got {r}")
    print(f"cache -> {out}")
    return 0 if all(ok for *_, ok in table) else 1


if __name__ == "__main__":
    sys.exit(main())
