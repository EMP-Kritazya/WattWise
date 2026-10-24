"""One test per `contracts/fixtures/rest/*.json`: send {method, path, request}, expect {status, response}.

Fixtures are compared as parsed JSON, never raw bytes.
"""

import json

import pytest

from api.settings import REPO_ROOT

REST_FILES = sorted((REPO_ROOT / "contracts" / "fixtures" / "rest").glob("*.json"))


@pytest.mark.parametrize("fixture_file", REST_FILES, ids=[f.stem for f in REST_FILES])
def test_rest_fixture(client, agent_token, fixture_file):
    fx = json.loads(fixture_file.read_text(encoding="utf-8"))
    kwargs = {"headers": {"X-Agent-Token": agent_token}}
    if fx["request"] is not None:
        kwargs["json"] = fx["request"]

    resp = client.request(fx["method"], fx["path"], **kwargs)

    assert resp.status_code == fx["status"], resp.text
    assert resp.json() == fx["response"]
