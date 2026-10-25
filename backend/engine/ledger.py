"""Owed-energy estimate from actual hub power; no synthetic energy is added to meter readings."""
from __future__ import annotations


class Ledger:
    def __init__(self) -> None:
        self.expected_kw: dict[str, float] = {}
        self._owed: dict[str, float] = {}

    def reduce(self, device_id: str, expected_kw: float) -> None:
        if device_id not in self.expected_kw or self._owed.get(device_id, 0.0) <= 1e-12:
            self.expected_kw[device_id] = expected_kw
        self._owed.setdefault(device_id, 0.0)

    def observe(self, actual_kw: dict[str, float], minutes: int, reduced: set[str]) -> None:
        for did, expected in self.expected_kw.items():
            if did not in actual_kw:
                continue
            delta = expected - actual_kw[did]
            if did in reduced:
                self._owed[did] = self.owed(did) + max(0.0, delta) * minutes / 60
            else:
                self._owed[did] = max(0.0, self.owed(did) - max(0.0, -delta) * minutes / 60)

    def owed(self, device_id: str) -> float:
        return self._owed.get(device_id, 0.0)
