"""The escalation council: when the engine escalates, the Concierge asks Weather, Grid and Events about THAT window before
Claude decides, with the existing endpoints and agent messages only (no contract change).

Watch: `GET /api/escalations?status=open` every COUNCIL_POLL_S (concierge.py); each open escalation is convened once.
Window: from the escalation's `ts` (sim now) to the end of its problem block (`block_start` + 15 min), plus 2 h, in whole
hours. The agent messages carry no start time, so the window is sent as `hours` / `window_h` counted from now.
Ask: the three agents in parallel, `reply_s` (4 real s) each. A silent agent is logged as error and left out; never blocks.
Post: the replies, numbers unchanged, as one partial `POST /api/context` (posts merge). The runtime hands Claude the
freshest context it holds (runtime/escalations.py waits up to COUNCIL_WAIT_S for this post).
Log: every request / response / error / post via `POST /api/agent-log`, each summary starting with "council e_XXXX: ".
Never raises.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from uagents import Model

from context_loop import API_TIMEOUT_S, RADIUS_KM, REGION, ApiClient, Asker, Location, iso_ms, utc_now
from models import EventsRequest, PriceRequest, WeatherRequest

log = logging.getLogger("agents.council")

BLOCK_MIN = 15  # one 15-min peak block (CONTRACTS.md Meter)
MARGIN_H = 2
REPLY_S = 4.0


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def window_hours(escalation: dict) -> int:
    """Whole hours from the escalation's `ts` to the end of its problem block, plus MARGIN_H."""
    end = _parse(escalation["block_start"]) + timedelta(minutes=BLOCK_MIN)
    seconds = max((end - _parse(escalation["ts"])).total_seconds(), 0.0)
    return math.ceil(seconds / 3600) + MARGIN_H


class Council:
    def __init__(self, http: httpx.AsyncClient, api: ApiClient, *, now: Callable[[], datetime] = utc_now,
                 reply_s: float = REPLY_S, region: str = REGION, radius_km: float = RADIUS_KM):
        self._http = http  # base_url = API_URL
        self._api = api
        self._now = now
        self.reply_s = reply_s
        self.region = region
        self.radius_km = radius_km
        self._seen: set[str] = set()  # open escalation ids already convened

    async def new_escalations(self) -> list[dict]:
        """Open escalations not convened yet. Ids no longer open are forgotten (a rebuilt kitchen restarts at e_0001)."""
        try:
            r = await self._http.get("/api/escalations", params={"status": "open"}, timeout=API_TIMEOUT_S)
        except httpx.HTTPError:
            return []
        if r.status_code != 200:
            return []
        open_now = r.json()
        fresh = [e for e in open_now if e["escalation_id"] not in self._seen]
        self._seen = {e["escalation_id"] for e in open_now}
        return fresh

    async def _log(self, tag: str, from_agent: str, to_agent: str, kind: str, summary: str) -> None:
        entry = {"ts_real": iso_ms(self._now()), "from_agent": from_agent, "to_agent": to_agent, "kind": kind,
                 "summary": f"{tag}: {summary}"}
        ok, why = await self._api.post("/api/agent-log", entry)
        if not ok:
            log.warning("agent log not posted (%s): %s", why, entry["summary"])

    async def _request(self, tag: str, ask: Asker, name: str, request: Model, summary: str) -> Model | None:
        await self._log(tag, "concierge", name, "request", summary)
        try:
            reply = await asyncio.wait_for(ask(name, request), self.reply_s)
        except Exception as e:  # timeout or a broken transport: the same as no answer
            log.warning("%s: asking %s failed: %r", tag, name, e)
            reply = None
        if reply is None:
            await self._log(tag, "concierge", name, "error", f"No reply from {name} within {self.reply_s:g} s; skipped")
        return reply

    async def convene(self, escalation: dict, where: Location, ask: Asker) -> dict | None:
        """One council. Returns the Context body posted, or None when nothing was posted."""
        tag = f"council {escalation['escalation_id']}"
        hours = window_hours(escalation)
        weather, prices, events = await asyncio.gather(
            self._request(tag, ask, "weather", WeatherRequest(lat=where.lat, lon=where.lon, hours=hours),
                          f"Forecast {hours} h for {where.lat:.2f},{where.lon:.2f} (block {escalation['block_start']})"),
            self._request(tag, ask, "grid", PriceRequest(region=self.region, hours=hours),
                          f"Prices {hours} h for {self.region} (block {escalation['block_start']})"),
            self._request(tag, ask, "events",
                          EventsRequest(lat=where.lat, lon=where.lon, radius_km=self.radius_km, window_h=hours),
                          f"Events within {self.radius_km:g} km in the next {hours} h"),
        )

        body: dict = {}
        if weather is not None:
            body["weather"] = weather.model_dump()
            await self._log(tag, "weather", "concierge", "response",
                            f"{len(weather.hourly)} hourly temperatures ({weather.label})")
        if prices is not None:
            body["prices"] = prices.model_dump()
            await self._log(tag, "grid", "concierge", "response",
                            f"{len(prices.hourly)} hourly prices, stress {prices.stress} ({prices.label})")
        if events is not None:
            body["events"] = events.model_dump()
            n = len(events.items)
            names = ", ".join(i.name for i in events.items)
            await self._log(tag, "events", "concierge", "response",
                            f"{n} event{'' if n == 1 else 's'}" + (f": {names}" if names else ""))

        if not body:
            await self._log(tag, "concierge", "engine", "error", "No agent answered; Claude decides on the last known context")
            return None
        ok, why = await self._api.post("/api/context", body)
        if not ok:
            await self._log(tag, "concierge", "engine", "error", f"POST /api/context failed ({why})")
            return None
        await self._log(tag, "concierge", "engine", "post", f"Context for the block posted ({', '.join(body)})")
        return body
