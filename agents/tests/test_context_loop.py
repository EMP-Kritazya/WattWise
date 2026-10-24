"""The Concierge context loop in recorded mode reproduces contracts/fixtures/agents/ exactly; any agent, Claude or the API
down degrades to "last known" without raising."""

import json
from datetime import datetime, timedelta, timezone

import httpx

import events
import grid
import weather
from common import FIXTURES_DIR, load_fixture
from context_loop import ApiClient, ContextLoop, Location
from crowd import recorded_classifier
from models import EventsRequest, PriceRequest, WeatherRequest

TOKEN = "test-agent-token"
FIXTURE_LOG = [json.loads(line) for line in (FIXTURES_DIR / "agent_log.jsonl").read_text(encoding="utf-8").splitlines()]
CONTEXT_POST = load_fixture("context_post.json")
WHERE = Location(lat=37.8, lon=-122.44)


class SteppingClock:
    """Each reading is 40 ms after the previous one (the fixture log's spacing)."""

    def __init__(self, start: datetime):
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(milliseconds=40)
        return self.t


class FakeApi:
    """Records every POST the loop makes; `fail` paths answer 404, `down` refuses every connection."""

    def __init__(self, fail: tuple[str, ...] = (), down: bool = False):
        self.posts: list[tuple[str, dict, dict]] = []
        self.fail, self.down = fail, down
        self.http = httpx.AsyncClient(base_url="http://api.test", transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        self.posts.append((request.url.path, dict(request.headers), json.loads(request.content)))
        if request.url.path in self.fail:
            return httpx.Response(404, json={"detail": "No kitchen"})
        return httpx.Response(200, json={"ok": True})

    def bodies(self, path: str) -> list[dict]:
        return [body for p, _, body in self.posts if p == path]


def recorded_asker(seen: list | None = None, down: tuple[str, ...] = ()):
    answers = {"weather": weather.answer, "grid": grid.answer, "events": events.answer}

    async def ask(name, request):
        if seen is not None:
            seen.append((name, request))
        if name in down:
            return None
        return await answers[name](request, use_recorded=True)

    return ask


def loop_with(api: FakeApi, start: datetime, classify=recorded_classifier) -> ContextLoop:
    return ContextLoop(ApiClient(api.http, TOKEN), classify, now=SteppingClock(start))


def without_ts(body: dict) -> dict:
    return {k: v for k, v in body.items() if k != "ts"}


async def test_recorded_rounds_reproduce_the_fixture_log_and_context_post():
    api, seen = FakeApi(), []
    loop = loop_with(api, datetime(2026, 10, 25, 17, 30, 0, tzinfo=timezone.utc))
    first = await loop.run_once(WHERE, recorded_asker(seen))
    loop._now = SteppingClock(datetime(2026, 10, 25, 17, 30, 30, tzinfo=timezone.utc))  # the fixture's second round
    second = await loop.run_once(WHERE, recorded_asker())

    assert api.bodies("/api/agent-log") == FIXTURE_LOG
    # One POST /api/context per round with crowd_effect inside; `ts` is left to the API (it stamps sim time).
    assert api.bodies("/api/context") == [without_ts(CONTEXT_POST["body"])] * 2
    assert first == second == without_ts(CONTEXT_POST["body"])
    assert {h["x-agent-token"] for _, h, _ in api.posts} == {TOKEN}
    # The context is posted after Claude's answer and before the "post" log line, as in the fixture.
    paths = [p for p, _, _ in api.posts][:10]
    assert paths == ["/api/agent-log"] * 8 + ["/api/context", "/api/agent-log"]
    # The requests are the recorded ones.
    assert [(n, r.model_dump()) for n, r in seen] == [
        ("weather", load_fixture("weather_request.json")),
        ("grid", load_fixture("price_request.json")),
        ("events", load_fixture("events_request.json")),
    ]


async def test_each_agent_recorded_answer_is_its_fixture():
    assert (await weather.answer(WeatherRequest(lat=1, lon=2, hours=6), use_recorded=True)).model_dump() \
        == load_fixture("weather_response.json")
    assert (await grid.answer(PriceRequest(region="caiso_np15", hours=6), use_recorded=True)).model_dump() \
        == load_fixture("price_response.json")
    assert (await events.answer(EventsRequest(lat=1, lon=2, radius_km=5, window_h=12), use_recorded=True)).model_dump() \
        == load_fixture("events_response.json")


async def test_an_agent_that_does_not_answer_is_left_out_and_logged():
    api = FakeApi()
    body = await loop_with(api, datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc)).run_once(
        WHERE, recorded_asker(down=("weather",)))
    assert "weather" not in body  # posts merge: the API keeps the last known weather
    assert body["prices"] == without_ts(CONTEXT_POST["body"])["prices"]
    logs = api.bodies("/api/agent-log")
    assert {k: logs[1][k] for k in ("from_agent", "to_agent", "kind")} == \
        {"from_agent": "concierge", "to_agent": "weather", "kind": "error"}
    assert logs[-1]["kind"] == "post"


async def test_claude_off_posts_no_crowd_effect_and_does_not_log_claude():
    api = FakeApi()
    body = await loop_with(api, datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc), classify=None).run_once(
        WHERE, recorded_asker())
    assert "crowd_effect" not in body
    assert "claude" not in {e["to_agent"] for e in api.bodies("/api/agent-log")}


async def test_claude_failing_keeps_the_last_crowd_effect_and_logs_an_error():
    async def no_answer(events_part):
        return None

    api = FakeApi()
    body = await loop_with(api, datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc), classify=no_answer).run_once(
        WHERE, recorded_asker())
    assert "crowd_effect" not in body
    assert [e["kind"] for e in api.bodies("/api/agent-log") if "claude" in (e["from_agent"], e["to_agent"])] == \
        ["request", "error"]


async def test_every_agent_down_posts_nothing():
    api = FakeApi()
    body = await loop_with(api, datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc)).run_once(
        WHERE, recorded_asker(down=("weather", "grid", "events")))
    assert body is None
    assert api.bodies("/api/context") == []


async def test_api_rejecting_or_down_never_raises():
    rejecting = FakeApi(fail=("/api/context",))
    loop = loop_with(rejecting, datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc))
    assert await loop.run_once(WHERE, recorded_asker()) is None
    assert rejecting.bodies("/api/agent-log")[-1]["kind"] == "error"
    assert loop.last_body is None

    down = FakeApi(down=True)
    assert await loop_with(down, datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc)).run_once(
        WHERE, recorded_asker()) is None


async def test_a_broken_transport_counts_as_no_answer():
    async def broken(name, request):
        raise RuntimeError("envelope lost")

    assert await loop_with(FakeApi(), datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc)).run_once(
        WHERE, broken) is None
