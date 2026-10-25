"""Shared id allocator (ENGINE.md section 0): one monotonically increasing counter per id type, shared by both lanes."""
from __future__ import annotations

ID_KINDS = ("d", "c", "e")  # Decision, Command, Escalation


class IdAllocator:
    """`d_0001`, `c_0001`, `e_0001`; zero-padded to 4 digits, wider when needed (`d_10000`). Never reset during a run."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {kind: 0 for kind in ID_KINDS}

    def next(self, kind: str) -> str:
        if kind not in self._counters:
            raise ValueError(f"unknown id kind {kind!r}")
        self._counters[kind] += 1
        return f"{kind}_{self._counters[kind]:04d}"

    def counters(self) -> dict[str, int]:
        """Last number issued per kind (0 = none yet)."""
        return dict(self._counters)
