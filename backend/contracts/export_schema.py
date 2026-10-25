"""Generate `contracts/ws_messages.schema.json` from the Pydantic models (never hand-edit the JSON).

    cd backend && python -m contracts.export_schema          # write
    cd backend && python -m contracts.export_schema --check  # exit 1 if the file is stale
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic.json_schema import models_json_schema

from .hub import HubToServerMessage, ServerToHubMessage
from .ws import ViewerMessage

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "ws_messages.schema.json"


def build_schema() -> dict:
    _, defs = models_json_schema(
        [
            (ViewerMessage, "validation"),
            (HubToServerMessage, "validation"),
            (ServerToHubMessage, "validation"),
        ],
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://wattwise.local/contracts/ws_messages.schema.json",
        "title": "WattWise WebSocket messages",
        "description": (
            "GENERATED from backend/contracts (python -m contracts.export_schema); do not hand-edit. "
            "Source of truth: docs/CONTRACTS.md sections 1, 2 (/ws viewer socket) and 8 (/ws/hub hub protocol). "
            "Validate a /ws frame against #/$defs/ViewerMessage, a hub frame against #/$defs/HubToServerMessage, "
            "a server frame on /ws/hub against #/$defs/ServerToHubMessage. Cross-field rules (limits per importance, "
            "peak_mode vs peak_cap_kw, option ranks, phase vs paused_reason) are enforced by the Pydantic models only."
        ),
        "oneOf": [
            {"$ref": "#/$defs/ViewerMessage"},
            {"$ref": "#/$defs/HubToServerMessage"},
            {"$ref": "#/$defs/ServerToHubMessage"},
        ],
        "$defs": dict(sorted(defs["$defs"].items())),
    }


def render() -> str:
    return json.dumps(build_schema(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        if current != text:
            print(f"{SCHEMA_PATH} is stale: run python -m contracts.export_schema", file=sys.stderr)
            return 1
        print("schema up to date")
        return 0
    SCHEMA_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
