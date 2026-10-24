"""Proposals: changes the AI suggests, applied by code only after an owner confirmation (CONTRACTS.md §1 Proposal).

Created by the `propose_*` tools (and by `choose_escalation_option` when the engine answers `awaiting_owner`), stored in
the store's `proposals` table, pushed as a `proposal` message on `/ws` at every change. Confirm paths: the UI
(`POST /api/proposals/{id}/confirm`), an ASI:One card button or a `confirm` / `yes` reply (`confirmed_via: "asi_one"`).
Applying = the normal facade call through the service (`set_importance`, `set_peak_cap`, `set_authority`, `undo`,
`resolve_escalation`) or scheduling a customer surge in the run loop. Never the model.

Times are sim time (the run loop's clock). A pending proposal expires PROPOSAL_TTL_MIN after it was made; an escalation
proposal at the escalation's deadline; a customer event no later than its start.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from api.errors import NotFoundError, RuleError

PROPOSAL_TTL_MIN = 30
CONFIRM_VIA = ("ui", "asi_one")
_ID = re.compile(r"^p_(\d+)$")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProposalBook:
    def __init__(
        self,
        service: Any,
        *,
        clock: Callable[[], str],
        publish: Callable[[dict], None],
        schedule_customer_event: Callable[[dict], None],
    ):
        self._service = service  # api.service.KitchenService: facade calls, store, the shared lock
        self._store = service.store
        self._clock = clock  # current sim time (RunLoop.sim_ts)
        self._publish = publish  # one /ws message, from any thread
        self._schedule_customer_event = schedule_customer_event  # RunLoop.schedule_customer_event

    # ------------------------------------------------------------ create

    def create(self, kind: str, payload: dict, summary: str) -> dict:
        with self._service.lock:
            now = self._clock()
            proposal = {
                "proposal_id": self._next_id(),
                "ts": now,
                "kind": kind,
                "payload": copy.deepcopy(payload),
                "summary": summary,
                "status": "pending",
                "created_by": "ai",
                "confirmed_via": None,
                "expires_at": self._expires_at(kind, payload, now),
            }
            self._store.upsert_proposal(proposal)
        self._push(proposal)
        return proposal

    def _next_id(self) -> str:
        numbers = [int(m.group(1)) for p in self._store.proposals() if (m := _ID.match(p["proposal_id"]))]
        return f"p_{max(numbers, default=0) + 1:04d}"

    def _expires_at(self, kind: str, payload: dict, now: str) -> str:
        expires = _parse(now) + timedelta(minutes=PROPOSAL_TTL_MIN)
        if kind == "resolve_escalation":
            escalation = next((e for e in self._service.escalations("open") + self._service.escalations("awaiting_owner")
                               if e["escalation_id"] == payload["escalation_id"]), None)
            if escalation is None:
                raise NotFoundError("open escalation", payload["escalation_id"])
            if payload["option_id"] not in {o["option_id"] for o in escalation["options"]}:
                raise RuleError(f"{payload['option_id']} is not an option of {payload['escalation_id']}")
            return escalation["deadline_sim_ts"]
        if kind == "customer_event":
            expires = min(expires, _parse(payload["start_sim_ts"]))
        return _iso(expires)

    # ------------------------------------------------------------ read

    def list(self, status: str | None = None) -> list[dict]:
        self.expire_due()
        return self._store.proposals(status)

    def latest_pending(self) -> dict | None:
        """The newest pending proposal (the target of a `confirm` / `yes` reply in ASI:One)."""
        pending = self.list("pending")
        return pending[-1] if pending else None

    def expire_due(self) -> list[dict]:
        """Pending proposals past `expires_at` (sim time) become `expired`."""
        now = _parse(self._clock())
        expired = []
        with self._service.lock:
            for proposal in self._store.proposals("pending"):
                if _parse(proposal["expires_at"]) <= now:
                    proposal["status"] = "expired"
                    self._store.upsert_proposal(proposal)
                    expired.append(proposal)
        for proposal in expired:
            self._push(proposal)
        return expired

    # ------------------------------------------------------------ confirm

    def confirm(self, proposal_id: str, confirm: bool, via: str = "ui") -> dict:
        if via not in CONFIRM_VIA:
            raise ValueError(f"confirmed_via={via!r}; expected one of {CONFIRM_VIA}")
        self.expire_due()
        # One lock for check-then-apply-then-write: UI and ASI:One confirming at once apply it once.
        with self._service.lock:
            proposal = self._store.proposal(proposal_id)
            if proposal is None:
                raise NotFoundError("proposal", proposal_id)
            if proposal["status"] != "pending":
                raise RuleError(f"{proposal_id} is {proposal['status']}, not pending")
            if confirm:
                self._apply(proposal)  # RuleError from the engine leaves it pending
                proposal.update(status="confirmed", confirmed_via=via)
            else:
                proposal["status"] = "cancelled"
            self._store.upsert_proposal(proposal)
        self._push(proposal)
        return proposal

    def _apply(self, proposal: dict) -> None:
        kind, payload, svc = proposal["kind"], proposal["payload"], self._service
        if kind == "importance":
            svc.set_importance(payload["device_id"], payload)
        elif kind == "peak_cap":
            svc.set_peak_cap(payload)
        elif kind == "authority":
            svc.set_authority(payload)
        elif kind == "undo_decision":
            svc.undo_decision(payload["decision_id"])
        elif kind == "resolve_escalation":
            svc.resolve_escalation(payload["escalation_id"], {"option_id": payload["option_id"]})
        elif kind == "customer_event":
            self._schedule_customer_event(payload)
        else:
            raise RuleError(f"unknown proposal kind {kind!r}")

    def _push(self, proposal: dict) -> None:
        self._publish({"type": "proposal", "data": copy.deepcopy(proposal)})
