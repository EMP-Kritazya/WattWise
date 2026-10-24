"""Fake sim host (`HUB_IMPL=fake`): plays the browser hub on `/ws/hub` from recorded fixtures (CONTRACTS.md §8).

Sends `hub_protocol/hub_hello.json`, then answers each `sim_tick` with the `hub_to_server.jsonl` line whose `tick_id`
matches. Replayed ticks (`replay: true`, after a reconnect) are answered only for the last one of the burst.
FAKE DATA: every HubReport is a recording, nothing is simulated here.

Run from backend/:  python -m fakes.fake_hub_client --url ws://localhost:8000/ws/hub
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

import websockets

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
# A replay burst arrives at full speed; this much silence after a replayed tick means it was the last one.
REPLAY_QUIET_S = 0.2

log = logging.getLogger("fake_hub_client")


def load_recording(fixtures_dir: Path) -> tuple[dict, dict[int, dict]]:
    """→ (hub_hello, {tick_id: hub_report message})."""
    hub_dir = fixtures_dir / "hub_protocol"
    hello = json.loads((hub_dir / "hub_hello.json").read_text(encoding="utf-8"))
    reports = {}
    for line in (hub_dir / "hub_to_server.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            msg = json.loads(line)
            if msg["type"] == "hub_report":
                reports[msg["tick_id"]] = msg
    return hello, reports


class FakeHubClient:
    def __init__(self, url: str, fixtures_dir: Path | None = None):
        self.url = url
        self.hello, self.reports = load_recording(Path(fixtures_dir or os.environ.get("FIXTURES_DIR") or DEFAULT_FIXTURES_DIR))
        self.answered: list[int] = []

    async def run(self) -> list[int]:
        """Connect and answer ticks until the server closes the socket. Returns the tick_ids answered."""
        async with websockets.connect(self.url) as ws:
            await ws.send(json.dumps(self.hello))
            pending_replay: int | None = None
            while True:
                try:
                    timeout = REPLAY_QUIET_S if pending_replay is not None else None
                    raw = await asyncio.wait_for(ws.recv(), timeout)
                except asyncio.TimeoutError:
                    await self._answer(ws, pending_replay)
                    pending_replay = None
                    continue
                except websockets.ConnectionClosed:
                    break
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "sim_tick" and msg.get("replay"):
                    pending_replay = msg["tick_id"]
                    continue
                if pending_replay is not None:
                    await self._answer(ws, pending_replay)
                    pending_replay = None
                if kind == "hub_welcome" and not msg.get("accepted"):
                    log.warning("not accepted as sim host: %s", msg.get("reason"))
                    break
                if kind == "sim_tick":
                    await self._answer(ws, msg["tick_id"])
                else:
                    log.info("received %s", kind)
        return self.answered

    async def _answer(self, ws, tick_id: int) -> None:
        report = self.reports.get(tick_id)
        if report is None:
            # No recording: stay silent and let the server pause with hub_waiting rather than invent a report.
            log.warning("no recorded hub_report for tick %s", tick_id)
            return
        await ws.send(json.dumps(report))
        self.answered.append(tick_id)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fake sim host: replays recorded hub_reports on /ws/hub")
    parser.add_argument("--url", default="ws://localhost:8000/ws/hub")
    parser.add_argument("--fixtures", type=Path, default=None, help="contracts/fixtures directory")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    answered = asyncio.run(FakeHubClient(args.url, args.fixtures).run())
    log.info("answered %d ticks", len(answered))


if __name__ == "__main__":
    main()
