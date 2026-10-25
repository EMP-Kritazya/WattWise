import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from runtime.live_port import RecordingLive
from api.settings import REPO_ROOT, Settings

AGENT_TOKEN = "test-agent-token"


@pytest.fixture
def agent_token():
    return AGENT_TOKEN


@pytest.fixture
def app():
    # Matches the state `rest/get_health.json` describes (sim host connected, Convex store).
    settings = Settings(
        kitchen_impl="fake", live_transport="spacetime", store="convex", hardware="off",
        agent_token=AGENT_TOKEN, fixtures_dir=REPO_ROOT / "contracts" / "fixtures",
    )
    app = create_app(settings)
    # API contract tests isolate hosted transport; the actual adapter has its own tests.
    app.state.live_port = RecordingLive()
    app.state.runtime.live.use(app.state.live_port)
    app.state.sim_host_connected = True
    app.state.runtime.hub_status = None  # as if the host were connected: the clock is not paused (no ticks are sent)
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
