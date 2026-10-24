import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))  # so `import engine.hub` works without a shared pytest config


@pytest.fixture(scope="session")
def catalog() -> list[dict]:
    return json.loads((BACKEND / "data" / "equipment_catalog.json").read_text())


@pytest.fixture
def demo_config(catalog) -> dict:
    """Demo Café: one of each type, catalog default importance and limits."""
    return {
        "name": "Demo Café",
        "equipment": [
            {"type_id": t["type_id"], "count": 1, "importance": t["default_importance"], "limits": t["default_limits"]}
            for t in catalog
        ],
        "peak_cap_kw": 40.0,
        "operating_hours": {"open": "10:00", "close": "22:00"},
        "seed": 42,
    }
