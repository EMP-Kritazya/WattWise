"""runtime/backtest_runner.py: Proof events published in contract order, paced, cached, one run at a time."""
from __future__ import annotations

import asyncio
import json

import pytest

from runtime.backtest_runner import CACHE_KIND, CACHE_VERSION, BacktestRunner, BacktestUnavailable


def _events(month: str, days: int) -> list[dict]:
    out = []
    for d in range(1, days + 1):
        out.append({"type": "backtest_point", "data": {"month": month, "day": f"{month}-{d:02d}", "saved_month_to_date_usd": d}})
    out.append({"type": "backtest_month", "data": {"month": month, "saved_usd": days}})
    out.append({"type": "backtest_progress", "month": month, "pct": 100})
    return out


def child_compute(months, assumptions_id, out):
    """Runs in a spawned process (module-level, so it pickles): the real runner's protocol with made-up events."""
    for m in months:
        for e in _events(m, 2):
            out.put(("event", e))
    out.put(("done", [{"month": m, "saved_usd": 2} for m in months]))


def child_fails(months, assumptions_id, out):
    out.put(("error", "RuntimeError: boom"))


class FakeStore:
    def __init__(self):
        self.saved: dict[str, list] = {}

    def backtest_run_ids(self):
        return list(self.saved)

    def save_backtest(self, run_id, results):
        self.saved[run_id] = results


class FakeLive:
    def __init__(self):
        self.calls: list[tuple] = []

    def send(self, method, *args):
        self.calls.append((method, *args))


class Clock:
    def __init__(self):
        self.t = 0.0
        self.waits: list[float] = []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.waits.append(round(s, 9))
        self.t += s


def write_cache(tmp_path, fp, months, events, results):
    (tmp_path / f"proof_{fp}.json").write_text(json.dumps({
        "kind": CACHE_KIND, "version": CACHE_VERSION, "fingerprint": fp, "months": months, "assumptions_id": "base",
        "events": events, "results": results}))


def make(tmp_path, *, month_s=3.0, compute_fn=child_compute, check=lambda m, a: None, clock=None):
    store, live, ws = FakeStore(), FakeLive(), []
    clock = clock or Clock()
    runner = BacktestRunner(store=store, live=live, publish_ws=ws.append, month_s=month_s, cache_dir=tmp_path,
                            compute_fn=compute_fn, fingerprint_fn=lambda m, a: "fp" + "".join(m) + a, check_fn=check,
                            sleep=clock.sleep, clock=clock.now)
    return runner, store, live, ws, clock


async def _finish(runner):
    await asyncio.wait_for(runner._run[1], 30)


async def test_cached_run_is_published_in_order_and_paced(tmp_path):
    write_cache(tmp_path, "fp2026-07base", ["2026-07"], _events("2026-07", 3), [{"month": "2026-07"}])
    runner, store, live, ws, clock = make(tmp_path, compute_fn=child_fails)  # the cache must be used, never computed
    assert await runner.start(["2026-07"], "base") == {"run_id": "run_0001"}
    await _finish(runner)
    assert live.calls[0] == ("reset_backtest", "run_0001")
    assert [c[0] for c in live.calls[1:]] == ["publish_backtest_point"] * 3 + ["publish_backtest_month"]
    assert [c[2]["day"] for c in live.calls[1:4]] == ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert clock.waits == [1.0, 1.0, 1.0]  # 3 s per month over its 3 points
    assert ws == [{"type": "backtest_progress", "run_id": "run_0001", "month": "2026-07", "pct": 100}]
    assert store.saved == {"run_0001": [{"month": "2026-07"}]}


async def test_computed_run_streams_from_a_separate_process_and_writes_the_cache(tmp_path):
    runner, store, live, _, _ = make(tmp_path, month_s=0.0)
    await runner.start(["2026-06", "2026-07"], "base")
    await _finish(runner)
    points = [c for c in live.calls if c[0] == "publish_backtest_point"]
    assert [p[2]["day"] for p in points] == ["2026-06-01", "2026-06-02", "2026-07-01", "2026-07-02"]
    assert store.saved["run_0001"] == [{"month": "2026-06", "saved_usd": 2}, {"month": "2026-07", "saved_usd": 2}]
    doc = json.loads((tmp_path / "proof_fp2026-062026-07base.json").read_text())
    assert doc["fingerprint"] == "fp2026-062026-07base" and len(doc["events"]) == 8 and doc["audited"] is False


async def test_second_press_while_playing_returns_the_same_run(tmp_path):
    write_cache(tmp_path, "fp2026-07base", ["2026-07"], _events("2026-07", 30), [])
    gate = asyncio.Event()

    class SlowClock(Clock):
        async def sleep(self, s):
            await gate.wait()

    runner, _, _, _, _ = make(tmp_path, clock=SlowClock())
    first = await runner.start(["2026-07"], "base")
    assert await runner.start(["2026-07"], "base") == first
    gate.set()
    await _finish(runner)
    assert (await runner.start(["2026-07"], "base"))["run_id"] == "run_0002"  # a finished run can be replayed
    await _finish(runner)


async def test_unavailable_data_is_refused_before_a_run_id_is_given(tmp_path):
    def refuse(months, assumptions_id):
        raise BacktestUnavailable("the backtest dataset is not on this server and no cached run exists")

    runner, store, live, _, _ = make(tmp_path, check=refuse)
    with pytest.raises(BacktestUnavailable, match="dataset"):
        await runner.start(["2026-07"], "base")
    assert live.calls == [] and store.saved == {}


async def test_a_failed_computation_saves_nothing_and_can_be_retried(tmp_path):
    runner, store, live, _, _ = make(tmp_path, compute_fn=child_fails)
    await runner.start(["2026-07"], "base")
    await _finish(runner)
    assert store.saved == {} and [c[0] for c in live.calls] == ["reset_backtest"]
    assert not list(tmp_path.glob("proof_*.json"))
    runner._compute_fn = child_compute
    await runner.start(["2026-07"], "base")
    await _finish(runner)
    assert list(store.saved) == ["run_0002"]


async def test_warm_fills_the_cache_without_publishing(tmp_path):
    runner, store, live, ws, _ = make(tmp_path, month_s=0.0)
    await asyncio.wait_for(runner.warm(["2026-07"], "base"), 30)
    assert live.calls == [] and ws == [] and store.saved == {}
    assert (tmp_path / "proof_fp2026-07base.json").exists()
