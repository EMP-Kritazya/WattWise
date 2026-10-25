"""Proof replay runner (CONTRACTS.md §2 `POST /api/backtest/run` + ws `backtest_progress`, §5 `backtest_point` /
`backtest_month`, DATA_AND_PROOF.md "Replay and backtest").

`start(months, assumptions_id)` answers with a run_id at once. The run's `on_progress` events (CONTRACTS.md §3
`run_backtest`) are published in order: points and month marks through the live port (SpacetimeDB rows, or the /ws
messages), progress as the /ws `backtest_progress` message (it has no table). Publishing is paced so a month plays in
`month_s` real seconds; the pace is display only and never slows the computation.

The replay is CPU-bound, so it runs in a separate process: in a thread it would hold the GIL and starve the run loop's
clock. A finished computation is cached under `data/backtest_cache/` (gitignored) with a fingerprint of everything that
decides its numbers (catalog, assumptions, tariff, engine and data code); the next run of the same months replays the
cache. `warm()` fills the cache at startup; a run started meanwhile follows that computation instead of starting another.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import multiprocessing
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("runtime.backtest_runner")

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "backtest_cache"
CACHE_KIND, CACHE_VERSION = "wattwise_proof_cache", 1
# Everything that decides a backtest number; a change to any of them invalidates the cache.
FINGERPRINT_FILES = ("data/equipment_catalog.json", "backtest/assumptions.yaml")
FINGERPRINT_DIRS = ("engine", "data", "contracts")


class BacktestUnavailable(ValueError):
    """The requested run cannot start (no cache and no dataset, unknown assumptions, a device above rated_kw)."""


def fingerprint(months: list[str], assumptions_id: str) -> str:
    h = hashlib.sha256(json.dumps([months, assumptions_id]).encode())
    paths = [BACKEND / f for f in FINGERPRINT_FILES]
    for d in FINGERPRINT_DIRS:
        paths += sorted((BACKEND / d).rglob("*.py"))
    for p in paths:
        h.update(str(p.relative_to(BACKEND)).encode())
        h.update(p.read_bytes())
    try:
        from backtest.assumptions import load_file, repo_path

        h.update(repo_path(load_file()["tariff"]["file"]).read_bytes())
    except (OSError, KeyError):
        h.update(b"no-tariff-file")
    return h.hexdigest()[:16]


def check_inputs(months: list[str], assumptions_id: str) -> None:
    """Cheap pre-flight in the request (about 1 s): the data loads for these months, else BacktestUnavailable."""
    from data.backtest_inputs import load_backtest_inputs
    from data.recipe import RatedKwExceeded

    try:
        load_backtest_inputs(months, assumptions_id)
    except FileNotFoundError as e:
        raise BacktestUnavailable(f"the backtest dataset is not on this server and no cached run exists ({e})") from e
    except (KeyError, RatedKwExceeded, ValueError) as e:
        raise BacktestUnavailable(str(e).strip('"')) from e


def compute(months: list[str], assumptions_id: str, out: Any) -> None:
    """Child process: load the inputs, run the engine's backtest, send every event, then the results."""
    try:
        os.nice(10)  # the live kitchen keeps priority on a small machine
    except (AttributeError, OSError):
        pass
    try:
        from data.backtest_inputs import load_backtest_inputs
        from engine import run_backtest

        inputs = load_backtest_inputs(months, assumptions_id)
        results = run_backtest(inputs, months, assumptions_id, on_progress=lambda e: out.put(("event", e)))
        out.put(("done", results))
    except BaseException as e:  # reported to the parent; the process ends either way
        out.put(("error", f"{type(e).__name__}: {e}"))


class _Job:
    """One computation (or cache) whose events any number of runs can follow."""

    def __init__(self, months: list[str], assumptions_id: str, fp: str) -> None:
        self.months, self.assumptions_id, self.fp = months, assumptions_id, fp
        self.events: list[dict] = []
        self.results: Optional[list[dict]] = None
        self.error: Optional[str] = None
        self.done = asyncio.Event()
        self._changed = asyncio.Condition()

    async def add(self, event: dict) -> None:
        async with self._changed:
            self.events.append(event)
            self._changed.notify_all()

    async def finish(self, results: Optional[list[dict]], error: Optional[str] = None) -> None:
        async with self._changed:
            self.results, self.error = results, error
            self.done.set()
            self._changed.notify_all()

    async def follow(self):
        """Every event in order, waiting for new ones until the job is done."""
        i = 0
        while True:
            async with self._changed:
                while i >= len(self.events) and not self.done.is_set():
                    await self._changed.wait()
                batch, finished = self.events[i:], self.done.is_set()
            for e in batch:
                yield e
            i += len(batch)
            if finished and i >= len(self.events):
                return


class BacktestRunner:
    def __init__(self, *, store: Any, live: Any, publish_ws: Callable[[dict], Any], month_s: float,
                 cache_dir: Path = DEFAULT_CACHE_DIR, compute_fn: Callable = compute,
                 fingerprint_fn: Callable[[list[str], str], str] = fingerprint,
                 check_fn: Callable[[list[str], str], None] = check_inputs,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Optional[Callable[[], float]] = None) -> None:
        self._store, self._live, self._publish_ws = store, live, publish_ws
        self._month_s = month_s
        self._cache_dir = Path(cache_dir)
        self._compute_fn, self._fingerprint, self._check = compute_fn, fingerprint_fn, check_fn
        self._sleep = sleep
        self._clock = clock
        self._jobs: dict[str, _Job] = {}  # fingerprint -> job (cached or computing)
        self._run: Optional[tuple[str, asyncio.Task]] = None
        self._tasks: set[asyncio.Task] = set()
        self._procs: set[Any] = set()
        self._next = len(store.backtest_run_ids())

    # ------------------------------------------------------------ public

    async def start(self, months: list[str], assumptions_id: str) -> dict:
        """→ `{run_id}`. A run already playing is answered with its own id (one Proof run at a time)."""
        if self._run is not None and not self._run[1].done():
            return {"run_id": self._run[0]}
        job = await self._job(list(months), assumptions_id, check=True)
        self._next += 1
        run_id = f"run_{self._next:04d}"
        task = self._spawn(self._play(run_id, job), name=f"backtest:{run_id}")
        self._run = (run_id, task)
        return {"run_id": run_id}

    async def warm(self, months: list[str], assumptions_id: str) -> None:
        """Fill the cache in the background (startup). Errors are logged: the Proof button reports them when pressed."""
        try:
            job = await self._job(list(months), assumptions_id, check=True)
            await job.done.wait()
        except BacktestUnavailable as e:
            log.warning("Proof cache not warmed: %s", e)

    async def stop(self) -> None:
        for p in list(self._procs):
            p.terminate()
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------ jobs

    async def _job(self, months: list[str], assumptions_id: str, *, check: bool) -> _Job:
        fp = await asyncio.to_thread(self._fingerprint, months, assumptions_id)
        job = self._jobs.get(fp)
        if job is not None and job.error is None:
            return job
        cached = await asyncio.to_thread(self._read_cache, fp)
        job = _Job(months, assumptions_id, fp)
        if cached is not None:
            job.events, job.results = cached["events"], cached["results"]
            job.done.set()
        else:
            if check:
                await asyncio.to_thread(self._check, months, assumptions_id)
            self._spawn(self._compute(job), name=f"backtest-compute:{fp}")
        self._jobs[fp] = job
        return job

    async def _compute(self, job: _Job) -> None:
        ctx = multiprocessing.get_context("spawn")
        out = ctx.Queue()
        proc = ctx.Process(target=self._compute_fn, args=(job.months, job.assumptions_id, out), daemon=True)
        proc.start()
        self._procs.add(proc)
        try:
            while True:
                kind, payload = await asyncio.to_thread(out.get)
                if kind == "event":
                    await job.add(payload)
                elif kind == "done":
                    job.results = payload
                    await asyncio.to_thread(self._write_cache, job)  # before `done`: a follower may check the cache
                    await job.finish(payload)
                    return
                else:
                    log.error("backtest computation failed: %s", payload)
                    await job.finish(None, payload)
                    return
        finally:
            self._procs.discard(proc)
            await asyncio.to_thread(proc.join, 5)

    # ------------------------------------------------------------ publishing

    async def _play(self, run_id: str, job: _Job) -> None:
        self._live.send("reset_backtest", run_id)
        loop = asyncio.get_running_loop()
        now = self._clock or loop.time
        due = now()
        days = {m: _days_in(m, job.events) for m in job.months}
        async for e in job.follow():
            kind = e["type"]
            if kind == "backtest_point":
                due = max(due, now()) + (self._month_s / max(1, days.get(e["data"]["month"], 30)) if self._month_s else 0)
                wait = due - now()
                if wait > 0:
                    await self._sleep(wait)
                self._live.send("publish_backtest_point", run_id, e["data"])
            elif kind == "backtest_month":
                self._live.send("publish_backtest_month", run_id, e["data"])
            elif kind == "backtest_progress":
                await _maybe_await(self._publish_ws({"type": "backtest_progress", "run_id": run_id,
                                                     "month": e["month"], "pct": e["pct"]}))
        if job.error is not None:
            log.error("Proof run %s stopped: %s", run_id, job.error)
            return
        await asyncio.to_thread(self._store.save_backtest, run_id, job.results or [])

    # ------------------------------------------------------------ cache

    def _cache_path(self, fp: str) -> Path:
        return self._cache_dir / f"proof_{fp}.json"

    def _read_cache(self, fp: str) -> Optional[dict]:
        p = self._cache_path(fp)
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if doc.get("kind") != CACHE_KIND or doc.get("version") != CACHE_VERSION or doc.get("fingerprint") != fp:
            return None
        return doc

    def _write_cache(self, job: _Job) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            doc = {"kind": CACHE_KIND, "version": CACHE_VERSION, "fingerprint": job.fp, "audited": False,
                   "months": job.months, "assumptions_id": job.assumptions_id,
                   "events": job.events, "results": job.results}
            tmp = self._cache_path(job.fp).with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self._cache_path(job.fp))
        except OSError:
            log.exception("could not write the Proof cache")

    def _spawn(self, coro, *, name: str) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task


def _days_in(month: str, events: list[dict]) -> int:
    """Points per month in a cached run; a calendar month's length while computing (pacing only)."""
    n = sum(1 for e in events if e["type"] == "backtest_point" and e["data"]["month"] == month)
    if n:
        return n
    y, m = int(month[:4]), int(month[5:])
    import calendar

    return calendar.monthrange(y, m)[1]


async def _maybe_await(value: Any) -> None:
    if asyncio.iscoroutine(value):
        await value
