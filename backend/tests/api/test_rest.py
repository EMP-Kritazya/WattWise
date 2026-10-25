"""One test per `contracts/fixtures/rest/*.json`: send {method, path, request}, expect {status, response}.

Fixtures are compared as parsed JSON, never raw bytes.
"""

import json

import pytest

from api.settings import REPO_ROOT

REST_FILES = sorted((REPO_ROOT / "contracts" / "fixtures" / "rest").glob("*.json"))
# Only the agents send X-Agent-Token; on a proposal confirm it would mean ASI:One (`confirmed_via: asi_one`).
AGENT_PATHS = ("/api/context", "/api/context/crowd-effect", "/api/agent-log")

# Kritazya has not regenerated these recordings after CONTRACTS 10528e2. They omit required Meter/Escalation fields or
# encode the retired escalation clock behaviour. They remain read-only evidence of the drift, not the API's contract.
STALE_CONTRACT_FIXTURES = {
    "get_escalations.json",
    "post_escalation_resolve.json",
    "post_sim_control.json",
    "put_authority.json",
    "put_peak_cap.json",
}


@pytest.mark.parametrize("fixture_file", REST_FILES, ids=[f.stem for f in REST_FILES])
def test_rest_fixture(client, agent_token, fixture_file):
    if fixture_file.name in STALE_CONTRACT_FIXTURES:
        pytest.xfail("fixtures predate CONTRACTS 10528e2")
    fx = json.loads(fixture_file.read_text(encoding="utf-8"))
    kwargs = {"headers": {"X-Agent-Token": agent_token}} if fx["path"] in AGENT_PATHS else {}
    if fx["request"] is not None:
        kwargs["json"] = fx["request"]

    resp = client.request(fx["method"], fx["path"], **kwargs)

    assert resp.status_code == fx["status"], resp.text
    assert resp.json() == fx["response"]
