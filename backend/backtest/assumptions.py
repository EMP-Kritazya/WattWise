"""Read `backtest/assumptions.yaml` (JSON-flow YAML with full-line `#` comments, see the file header)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ASSUMPTIONS_FILE = Path(__file__).resolve().parent / "assumptions.yaml"
REPO_ROOT = Path(__file__).resolve().parents[2]
KNOBS = ("flex_scale", "draw_scale", "forecast_noise_pct")


def parse(text: str) -> dict:
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return json.loads(body)


@lru_cache(maxsize=4)
def load_file(path: str = str(ASSUMPTIONS_FILE)) -> dict:
    return parse(Path(path).read_text(encoding="utf-8"))


def resolve(assumptions_id: str, doc: dict | None = None) -> dict[str, Any]:
    """The assumption set with `inherits` applied (child keys win). Unknown id -> KeyError."""
    doc = doc if doc is not None else load_file()
    sets = doc["assumptions"]
    if assumptions_id not in sets:
        raise KeyError(f"unknown assumptions_id {assumptions_id!r} (known: {', '.join(sets)})")
    chain, seen, cur = [], set(), assumptions_id
    while cur is not None:
        if cur in seen:
            raise ValueError(f"assumptions inherit cycle at {cur!r}")
        seen.add(cur)
        chain.append(sets[cur])
        cur = sets[cur].get("inherits")
    out: dict[str, Any] = {}
    for entry in reversed(chain):
        out.update({k: v for k, v in entry.items() if k != "inherits"})
    out["assumptions_id"] = assumptions_id
    return out


def knobs(resolved: dict) -> dict:
    """BacktestInputs.assumptions (CONTRACTS.md section 1): the knobs the engine applies itself."""
    return {"assumptions_id": resolved["assumptions_id"], **{k: float(resolved[k]) for k in KNOBS}}


def repo_path(relative: str) -> Path:
    return REPO_ROOT / relative
