"""`serve` fixture: a real server on a free port with the runtime wired as in production, plus the fake sim host."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn

from api.main import create_app
from api.settings import REPO_ROOT, Settings
from fakes.fake_hub_client import FakeHubClient

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
AGENT_TOKEN = "test-agent-token"


async def until(predicate, timeout=3.0):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), timeout)


class Server:
    def __init__(self, app, port):
        self.app, self.port = app, port
        self.runtime = app.state.runtime
        self.base = f"http://127.0.0.1:{port}"
        self.hub_url = f"ws://127.0.0.1:{port}/ws/hub"
        self.ws_url = f"ws://127.0.0.1:{port}/ws"
        self.http = httpx.AsyncClient(base_url=self.base, headers={"X-Agent-Token": AGENT_TOKEN})
        self.hub_client: FakeHubClient | None = None
        self.hub_task: asyncio.Task | None = None

    async def connect_fake_hub(self):
        self.hub_client = FakeHubClient(self.hub_url, FIXTURES)
        self.hub_task = asyncio.create_task(self.hub_client.run())
        await until(lambda: self.app.state.hub.connected)


@asynccontextmanager
async def _serve(**settings):
    app = create_app(Settings(kitchen_impl="fake", store="memory", fixtures_dir=FIXTURES, agent_token=AGENT_TOKEN,
                              **settings))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    await until(lambda: server.started)
    s = Server(app, server.servers[0].sockets[0].getsockname()[1])
    try:
        yield s
    finally:
        await s.http.aclose()
        await app.state.runtime.stop()
        server.should_exit = True
        await task
        if s.hub_task is not None:
            await asyncio.wait_for(s.hub_task, 3)


@pytest.fixture
def serve():
    return _serve
