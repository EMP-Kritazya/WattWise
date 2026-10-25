"""Meter on the fixture streams (ENGINE.md section 1 vs contracts/fixtures): the engine's Meter of every step equals the
fixture generator's engine-style meter to rounding (≤ 0.005; the fixtures publish kW / $ to 0.01, kWh to 0.001), including
`demand_peaks`, on both lanes.

Two streams: the committed `facade/step_stream.jsonl` (120 ticks × 2 lanes) and a full `generate.py --days 2` run (1710
ticks × 2 lanes, overnight included) written to a temp dir. Only the Meter is compared: the generator's toy decider issues
commands the engine does not issue yet (decider not built), which changes nothing the meter reads (it meters HubReports).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from contracts import WarmUpHistory
from engine import Kitchen

from tests.engine.conftest import FIXTURES, REPO_ROOT, catalog

TOL = 0.0051  # half of the fixture's last published digit (0.01), plus float noise
FLOAT_FIELDS = ("total_kw", "month_peak_kw", "on_peak_month_peak_kw", "target_kw", "energy_kwh_today",
                "energy_kwh_month", "price_usd_per_kwh_now", "cost_usd_today", "cost_usd_month")
EXACT_FIELDS = ("ts", "block_start", "peak_mode", "peak_cap_kw")


def _lanes():
    scenario = json.loads((FIXTURES / "scenario" / "demo_cafe" / "scenario.json").read_text())
    lanes = Kitchen.build_lanes(scenario["config"], scenario["tariff"], catalog(), scenario["seed"])
    history = WarmUpHistory.model_validate(json.loads((FIXTURES / scenario["warm_up"]["history"]).read_text()))
    plain = history.model_dump(mode="json")
    for lane in ("without", "with"):
        lanes[lane].warm_up(plain)
    return lanes


def compare_meter(got: dict, want: dict, where: str) -> None:
    for f in EXACT_FIELDS:
        assert got[f] == want[f], (where, f, got[f], want[f])
    for f in FLOAT_FIELDS:
        if want[f] is None or got[f] is None:
            assert got[f] == want[f], (where, f, got[f], want[f])
        else:
            assert abs(got[f] - want[f]) <= TOL, (where, f, got[f], want[f])
    # block_avg_kw: open reading GAPS 2 (fixtures: mean of the metered minutes so far; ENGINE.md section 1 and the
    # hand tests in test_meter.py: block energy ÷ 0.25 h). The two agree when the block closes, so compare it there only.
    if got["ts"][14:16] in ("00", "15", "30", "45"):
        assert abs(got["block_avg_kw"] - want["block_avg_kw"]) <= TOL, (where, "block_avg_kw", got, want)
    assert [d["name"] for d in got["demand_peaks"]] == [d["name"] for d in want["demand_peaks"]], where
    for g, w in zip(got["demand_peaks"], want["demand_peaks"]):
        assert g["usd_per_kw"] == w["usd_per_kw"], (where, g, w)
        assert abs(g["peak_kw"] - w["peak_kw"]) <= TOL, (where, g, w)
        assert abs(g["cost_usd"] - w["cost_usd"]) <= TOL, (where, g, w)


def replay_step_stream(path: Path) -> int:
    lanes = _lanes()
    n = 0
    with path.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            report = rec["args"]["hub_report"]
            got = lanes[report["lane"]].step(rec["args"]["minutes"], report)
            compare_meter(got["meter"], rec["returns"]["meter"], f"{report['lane']} tick {report['tick_id']}")
            n += 1
    return n


def test_committed_step_stream_meter_matches_to_rounding():
    assert replay_step_stream(FIXTURES / "facade" / "step_stream.jsonl") == 240


@pytest.mark.slow
def test_generated_two_day_run_meter_matches_to_rounding(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    proc = subprocess.run([sys.executable, str(FIXTURES / "generate.py"), "--days", "2", "--out", str(out)],
                          cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert replay_step_stream(out / "step_stream.jsonl") == 2 * 1710
