"""The escalation council: a new open escalation → Weather, Grid and Events asked in parallel for its window → one
POST /api/context with their replies unchanged, every message logged as "council e_XXXX". Silent agents are skipped."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from common import load_fixture
from context_loop import ApiClient, Location
from council import Council, window_hours
from test_context_loop import TOKEN, SteppingClock, recorded_asker

SHAPES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "shapes"
OPEN = json.loads((SHAPES / "escalation_open.json").read_text(encoding="utf-8"))  # e_0001, ts 01:30, block 01:45
WHERE = Location(lat=37.8, lon=-122.44)
START = datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc)


class FakeApi:
    """GET /api/escalations answers `open`; every POST is recorded, in order."""

    def __init__(self, open_escalations=(), down=False):
        self.open = list(open_escalations)
        self.down = down
        self.posts: list[tuple[str, dict]] = []
        self.http = httpx.AsyncClient(base_url="http://api.test", transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        if request.method == "GET":
            assert request.url.path == "/api/escalations" and request.url.params["status"] == "open"
            return httpx.Response(200, json=self.open)
        self.posts.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    def bodies(self, path):
        return [b for p, b in self.posts if p == path]


def council_with(api, reply_s=4.0):
    return Council(api.http, ApiClient(api.http, TOKEN), now=SteppingClock(START), reply_s=reply_s)


def silent_on(*names, then=recorded_asker()):
    """`then` answers, except `names`, which never reply (the council's budget runs out)."""

    async def ask(name, request):
        if name in names:
            await asyncio.sleep(10)
        return await then(name, request)

    return ask


def test_window_covers_the_problem_block_plus_two_hours():
    assert window_hours(OPEN) == 3  # 01:30 → block end 02:00 is 30 min → 1 h, + 2 h
    assert window_hours({**OPEN, "block_start": "2026-07-18T03:00:00Z"}) == 4  # 01:30 → 03:15 → 2 h, + 2 h


async def test_each_open_escalation_is_convened_once():
    api = FakeApi([OPEN])
    council = council_with(api)
    assert [e["escalation_id"] for e in await council.new_escalations()] == ["e_0001"]
    assert await council.new_escalations() == []
    api.open = []
    assert await council.new_escalations() == []
    api.open = [OPEN]  # a rebuilt kitchen restarts at e_0001: convened again
    assert [e["escalation_id"] for e in await council.new_escalations()] == ["e_0001"]


async def test_api_down_means_no_escalations_and_no_raise():
    assert await council_with(FakeApi(down=True)).new_escalations() == []


async def test_all_agents_answer_window_requests_then_one_context_post():
    api, seen = FakeApi(), []
    body = await council_with(api).convene(OPEN, WHERE, recorded_asker(seen))

    # Three requests for the escalation's window (3 h), in parallel.
    assert sorted((n, r.model_dump()) for n, r in seen) == [
        ("events", {"lat": 37.8, "lon": -122.44, "radius_km": 5, "window_h": 3}),
        ("grid", {"region": "caiso_np15", "hours": 3}),
        ("weather", {"lat": 37.8, "lon": -122.44, "hours": 3}),
    ]
    # The replies are posted unchanged, once, before the "post" log line.
    want = {"weather": load_fixture("weather_response.json"), "prices": load_fixture("price_response.json"),
            "events": load_fixture("events_response.json")}
    assert body == want and api.bodies("/api/context") == [want]
    paths = [p for p, _ in api.posts]
    assert paths.index("/api/context") == len(paths) - 2 and paths[-1] == "/api/agent-log"

    logs = api.bodies("/api/agent-log")
    assert all(e["summary"].startswith("council e_0001: ") for e in logs)
    assert sorted((e["from_agent"], e["to_agent"], e["kind"]) for e in logs) == sorted([
        ("concierge", "weather", "request"), ("concierge", "grid", "request"), ("concierge", "events", "request"),
        ("weather", "concierge", "response"), ("grid", "concierge", "response"), ("events", "concierge", "response"),
        ("concierge", "engine", "post"),
    ])


async def test_one_silent_agent_is_logged_as_error_and_skipped():
    api = FakeApi()
    loop = asyncio.get_running_loop()
    started = loop.time()
    body = await council_with(api, reply_s=0.1).convene(OPEN, WHERE, silent_on("weather"))
    assert loop.time() - started < 2  # the budget, not the agent's 10 s
    assert set(body) == {"prices", "events"}
    errors = [e for e in api.bodies("/api/agent-log") if e["kind"] == "error"]
    assert [(e["to_agent"], e["summary"]) for e in errors] == [
        ("weather", "council e_0001: No reply from weather within 0.1 s; skipped")]


async def test_all_silent_posts_nothing_and_logs_it():
    api = FakeApi()
    assert await council_with(api, reply_s=0.05).convene(OPEN, WHERE, silent_on("weather", "grid", "events")) is None
    assert api.bodies("/api/context") == []
    logs = api.bodies("/api/agent-log")
    assert [e["kind"] for e in logs].count("error") == 4  # three silent agents + nothing to post
    assert logs[-1]["to_agent"] == "engine"


async def test_a_broken_transport_is_the_same_as_silence():
    async def broken(name, request):
        raise RuntimeError("mailbox down")

    api = FakeApi()
    assert await council_with(api).convene(OPEN, WHERE, broken) is None


async def test_api_down_never_raises():
    api = FakeApi(down=True)
    assert await council_with(api).convene(OPEN, WHERE, recorded_asker()) is None
