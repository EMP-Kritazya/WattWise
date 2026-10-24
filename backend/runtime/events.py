"""Customer surges waiting for the next `sim_tick` (CONTRACTS.md §8: a surge appears once, in the tick where it starts).

Two doors: `POST /api/events/customers` (`add`) and the SpacetimeDB `surge_request` rows the judges' phones insert
(`add_requests`, read each tick through the live port). Each surge gets the next `s_NNNN` id and is handed out by
`drain()` exactly once; a request row seen again before its `consume_surge` lands is ignored.
A confirmed `customer_event` proposal is held (`add_at`) until the tick whose minute reaches its `start_sim_ts`.
"""

from __future__ import annotations


class SurgeQueue:
    def __init__(self) -> None:
        self._pending: list[dict] = []
        self._scheduled: list[tuple[str, int, int]] = []  # (start_sim_ts, customers, duration_min), by start
        self._seen_requests: set[int] = set()
        self._count = 0

    def add(self, customers: int, duration_min: int) -> dict:
        self._count += 1
        surge = {"surge_id": f"s_{self._count:04d}", "customers": customers, "duration_min": duration_min}
        self._pending.append(surge)
        return surge

    def add_at(self, start_sim_ts: str, customers: int, duration_min: int) -> None:
        """A surge that starts later: queued (and given its id) by the first `drain(sim_ts)` at or after its start."""
        self._scheduled.append((start_sim_ts, customers, duration_min))
        self._scheduled.sort(key=lambda s: s[0])

    def add_requests(self, rows: list[dict]) -> list[int]:
        """Queue unconsumed `surge_request` rows not seen before. Returns their ids (to `consume_surge`)."""
        taken = []
        for row in sorted(rows, key=lambda r: r["id"]):
            if row.get("consumed") or row["id"] in self._seen_requests:
                continue
            self._seen_requests.add(row["id"])
            self.add(row["customers"], row["duration_min"])
            taken.append(row["id"])
        return taken

    def drain(self, sim_ts: str | None = None) -> list[dict]:
        """Every surge for the tick whose minute starts at `sim_ts` (ISO UTC, same format as `start_sim_ts`)."""
        while self._scheduled and sim_ts is not None and self._scheduled[0][0] <= sim_ts:
            _, customers, duration_min = self._scheduled.pop(0)
            self.add(customers, duration_min)
        surges, self._pending = self._pending, []
        return surges

    def reset(self) -> None:
        """New kitchen: forget pending surges and restart ids. Seen request ids stay seen (the rows are not re-read)."""
        self._pending = []
        self._scheduled = []
        self._count = 0
