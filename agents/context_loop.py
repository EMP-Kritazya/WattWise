"""The Concierge's context loop (AGENTS.md "Concierge loops"): one round = ask Weather, Grid, Events → one narrow Claude
call for the crowd effect → one `POST /api/context` with the replies reshaped into Context, numbers unchanged.

Every message is logged with `POST /api/agent-log` (kind request | response | post | error) as it happens.
Graceful degradation: an agent that does not answer is left out of the post (posts merge, so the API keeps the last known
part); Claude off or failing → no crowd_effect in the post (last known kept); the API down → logged, nothing raised.
`ts` is not sent: the API stamps it in sim time.

Transport-free so tests can drive it: `run_once(where, ask)` takes `ask(agent_name, request)`, the uAgents round trip in
`concierge.py`; `now` is the real clock for `ts_real`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx
from uagents import Model

from crowd import Classifier
from models import EventsRequest, PriceRequest, WeatherRequest

log = logging.getLogger("agents.context_loop")

Asker = Callable[[str, Model], Awaitable[Model | None]]  # (agent name, request) → reply, or None (no answer in time)

HOURS = 6
REGION = "caiso_np15"
RADIUS_KM = 5
WINDOW_H = 12
API_TIMEOUT_S = 5.0


def iso_ms(dt: datetime) -> str:
    """`2026-10-25T17:30:00.040Z` (AgentLog.ts_real)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApiClient:
    """The two agent endpoints the loop posts to, with `X-Agent-Token`. Never raises: returns ok / not ok."""

    def __init__(self, http: httpx.AsyncClient, token: str | None):
        self._http = http  # base_url = API_URL
        self._headers = {"X-Agent-Token": token or ""}

    async def post(self, path: str, body: dict) -> tuple[bool, str]:
        try:
            r = await self._http.post(path, json=body, headers=self._headers, timeout=API_TIMEOUT_S)
        except httpx.HTTPError as e:
            return False, f"{type(e).__name__}"
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        return True, ""


@dataclass
class Location:
    lat: float
    lon: float


def _events_summary(items: list[dict]) -> str:
    n = len(items)
    names = ", ".join(i["name"] for i in items)
    return f"{n} event{'' if n == 1 else 's'}" + (f": {names}" if names else "")


class ContextLoop:
    def __init__(self, api: ApiClient, classify: Classifier | None, *,
                 now: Callable[[], datetime] = utc_now, hours: int = HOURS, region: str = REGION,
                 radius_km: float = RADIUS_KM, window_h: int = WINDOW_H):
        self._api = api
        self._classify = classify
        self._now = now
        self.hours = hours
        self.region = region
        self.radius_km = radius_km
        self.window_h = window_h
        self.last_body: dict | None = None  # the last Context posted

    async def _log(self, from_agent: str, to_agent: str, kind: str, summary: str) -> None:
        entry = {"ts_real": iso_ms(self._now()), "from_agent": from_agent, "to_agent": to_agent, "kind": kind,
                 "summary": summary}
        ok, why = await self._api.post("/api/agent-log", entry)
        if not ok:
            log.warning("agent log not posted (%s): %s", why, summary)

    async def _request(self, ask: Asker, name: str, request: Model, summary: str) -> Model | None:
        await self._log("concierge", name, "request", summary)
        try:
            reply = await ask(name, request)
        except Exception as e:  # a broken transport is the same as no answer
            log.warning("asking %s failed: %s", name, e)
            reply = None
        if reply is None:
            await self._log("concierge", name, "error", f"No reply from {name}; last known kept")
        return reply

    async def run_once(self, where: Location, ask: Asker) -> dict | None:
        """One round. Returns the Context body posted, or None when nothing was posted."""
        body: dict = {}

        weather = await self._request(ask, "weather", WeatherRequest(lat=where.lat, lon=where.lon, hours=self.hours),
                                      f"Forecast {self.hours} h for {where.lat:.2f},{where.lon:.2f}")
        if weather is not None:
            body["weather"] = weather.model_dump()
            await self._log("weather", "concierge", "response",
                            f"{len(weather.hourly)} hourly temperatures ({weather.label})")

        prices = await self._request(ask, "grid", PriceRequest(region=self.region, hours=self.hours),
                                     f"Prices {self.hours} h for {self.region}")
        if prices is not None:
            body["prices"] = prices.model_dump()
            await self._log("grid", "concierge", "response",
                            f"{len(prices.hourly)} hourly prices, stress {prices.stress} ({prices.label})")

        events = await self._request(
            ask, "events",
            EventsRequest(lat=where.lat, lon=where.lon, radius_km=self.radius_km, window_h=self.window_h),
            f"Events within {self.radius_km:g} km in the next {self.window_h} h")
        if events is not None:
            body["events"] = events.model_dump()
            await self._log("events", "concierge", "response", _events_summary(body["events"]["items"]))

        if events is not None and self._classify is not None:
            n = len(events.items)
            await self._log("concierge", "claude", "request", f"Classify crowd effect for {n} event{'' if n == 1 else 's'}")
            crowd = await self._classify(body["events"])
            if crowd is None:
                await self._log("concierge", "claude", "error", "No crowd effect from claude; last known kept")
            else:
                body["crowd_effect"] = {"value": crowd["value"], "set_by": "claude", "reason": crowd["reason"]}
                await self._log("claude", "concierge", "response", f"crowd_effect {crowd['value']}")

        if not body:
            return None
        ok, why = await self._api.post("/api/context", body)
        if not ok:
            await self._log("concierge", "engine", "error", f"POST /api/context failed ({why})")
            return None
        self.last_body = body
        await self._log("concierge", "engine", "post", "Context posted to /api/context")
        return body
