"""WattWise Events agent (tier 2): events near the kitchen in the next hours.

EventsRequest {lat, lon, radius_km, window_h} → EventsResponse {items[...], source, label}.
Live: Ticketmaster Discovery API v2 (key `TICKETMASTER_API_KEY`): name, venue, start and distance pass through unchanged,
source `ticketmaster`, label `live_api`. Ticketmaster publishes no attendance, and none is ever estimated here.
No key, timeout, HTTP error or rate limit → the recorded event, label `recorded`, logged as an error.
`--recorded` / DEMO_MODE=1: the recorded fixture (the scripted Giants game the demo needs), label `recorded`.
Chat (Agent Chat Protocol, for any ASI:One user or agent): "events tonight" -> the events as plain text with their label,
start in local time (America/Los_Angeles) next to UTC.

Run:  python agents/events.py [--recorded]      (seed: EVENTS_AGENT_SEED, or derived from FETCH_AGENT_SEED)
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from uagents import Context, Protocol

from common import load_dotenv, load_fixture, make_agent, recorded_mode
from models import EventsRequest, EventsResponse
from public_chat import DEFAULT_LAT, DEFAULT_LON, DEFAULT_PLACE, make_chat_protocol, parse_hours, when

log = logging.getLogger("agents.events")

TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
SOURCE = "ticketmaster"
TIMEOUT_S = 5.0
PAGE_SIZE = 20
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
CHAT_RADIUS_KM = 5.0
CHAT_DEFAULT_HOURS = 12
CHAT_MAX_HOURS = 24


@dataclass(frozen=True)
class ListedEvent:
    """One event as its source gave it. Fields the source does not publish stay None (never estimated)."""
    name: str
    venue: str | None
    start: str | None  # ISO 8601 UTC
    distance_km: float | None
    expected_attendance: int | None  # Ticketmaster: always None


@dataclass(frozen=True)
class EventsListing:
    items: list[ListedEvent]
    source: str
    label: str  # live_api | recorded


def recorded() -> EventsResponse:
    return EventsResponse.model_validate(load_fixture("events_response.json"))


def recorded_listing() -> EventsListing:
    reply = recorded()
    return EventsListing([ListedEvent(e.name, e.venue, e.start, e.distance_km, e.expected_attendance) for e in reply.items],
                         reply.source, reply.label)


def from_ticketmaster(payload: dict) -> EventsListing:
    """Discovery API v2 events JSON → listing, fields unchanged. No `_embedded` means no events."""
    items = []
    for e in (payload.get("_embedded") or {}).get("events", []):
        venues = (e.get("_embedded") or {}).get("venues") or [{}]
        distance = e.get("distance")
        items.append(ListedEvent(
            name=e["name"],
            venue=venues[0].get("name"),
            start=((e.get("dates") or {}).get("start") or {}).get("dateTime"),
            distance_km=float(distance) if distance is not None else None,  # requested with unit=km
            expected_attendance=None,
        ))
    return EventsListing(items, SOURCE, "live_api")


def utc_param(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def fetch_live(req: EventsRequest, key: str, client: httpx.AsyncClient, now: datetime) -> EventsListing:
    params = {
        "apikey": key,
        "latlong": f"{req.lat},{req.lon}",
        "radius": math.ceil(req.radius_km),  # Ticketmaster takes whole km only; rounding up misses no event
        "unit": "km",
        "startDateTime": utc_param(now),
        "endDateTime": utc_param(now + timedelta(hours=req.window_h)),
        "sort": "date,asc",
        "size": PAGE_SIZE,
    }
    r = await client.get(TICKETMASTER_URL, params=params, timeout=TIMEOUT_S)
    r.raise_for_status()
    return from_ticketmaster(r.json())


async def listing(req: EventsRequest, *, use_recorded: bool, client: httpx.AsyncClient | None = None,
                  now: datetime | None = None) -> EventsListing:
    """Live Ticketmaster events, or the recorded event (recorded mode, or any live failure, logged as an error)."""
    if use_recorded:
        return recorded_listing()
    key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    if not key:
        log.error("TICKETMASTER_API_KEY not set; answering with the recorded event")
        return recorded_listing()
    now = now or datetime.now(timezone.utc)
    try:
        if client is not None:
            return await fetch_live(req, key, client, now)
        async with httpx.AsyncClient() as own:
            return await fetch_live(req, key, own, now)
    except httpx.HTTPStatusError as e:  # the message carries the URL (and the key): log the status only
        log.error("Ticketmaster HTTP %s%s; answering with the recorded event", e.response.status_code,
                  " (rate limited)" if e.response.status_code == 429 else "")
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        log.error("Ticketmaster failed (%s); answering with the recorded event", type(e).__name__)
    return recorded_listing()


async def answer(req: EventsRequest, *, use_recorded: bool) -> EventsResponse:
    # STUB: contract question "may expected_attendance be null?" (CONTRACTS.md §1 Context.events, §7). The contract needs
    # an int and Ticketmaster publishes none, so the typed reply (the Concierge's context) stays the recorded event,
    # labeled `recorded`, until the contract allows null. Chat uses the live events (`listing`).
    return recorded()


proto = Protocol(name="wattwise-events", version="0.1.0")
RECORDED = False


@proto.on_message(EventsRequest, replies=EventsResponse)
async def on_request(ctx: Context, sender: str, req: EventsRequest):
    await ctx.send(sender, await answer(req, use_recorded=RECORDED))


def local_and_utc(ts: str | None) -> str:
    """"2026-07-18T02:05:00Z" → "2026-07-17 19:05 PDT (2026-07-18 02:05 UTC)"."""
    if ts is None:
        return "start time not published"
    try:
        local = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    except ValueError:
        return ts
    return f"{local:%Y-%m-%d %H:%M %Z} ({when(ts)})"


def event_line(e: ListedEvent) -> str:
    venue = e.venue if e.venue is not None else "venue not published"
    distance = f"{e.distance_km} km away" if e.distance_km is not None else "distance not published"
    attendance = (f"expected attendance {e.expected_attendance}" if e.expected_attendance is not None
                  else "attendance not published")
    return f"- {e.name} at {venue}, {local_and_utc(e.start)}, {distance}, {attendance}"


def chat_text(hours: int, reply: EventsListing) -> str:
    """The reply as plain text: every event as the source gave it, start in local time and UTC, with the label."""
    head = f"WattWise Events: near {DEFAULT_PLACE}, next {hours} h ({reply.label}, source {reply.source})"
    if not reply.items:
        return head + ": no events found."
    return "\n".join([head + ":"] + [event_line(e) for e in reply.items])


async def answer_text(text: str, client: httpx.AsyncClient | None = None, now: datetime | None = None) -> str:
    # STUB: chat always asks for the demo location; a place named in the message is not looked up yet.
    hours = parse_hours(text, CHAT_DEFAULT_HOURS, CHAT_MAX_HOURS)
    req = EventsRequest(lat=DEFAULT_LAT, lon=DEFAULT_LON, radius_km=CHAT_RADIUS_KM, window_h=hours)
    return chat_text(hours, await listing(req, use_recorded=RECORDED, client=client, now=now))


def main() -> None:
    global RECORDED
    load_dotenv()
    RECORDED = recorded_mode()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO line prints the request URL, apikey included
    agent = make_agent("events", "WattWise Events",
                       "Events near a restaurant in the next hours (Ticketmaster, live; recorded demo data for San "
                       "Francisco as fallback). Ask in plain text, e.g. 'events tonight', or send a typed EventsRequest.")
    agent.include(proto, publish_manifest=True)
    agent.include(make_chat_protocol(answer_text), publish_manifest=True)

    @agent.on_event("startup")
    async def announce(ctx: Context):
        ctx.logger.info(f"WattWise Events address: {agent.address} ({'recorded' if RECORDED else 'live'})")

    agent.run()


if __name__ == "__main__":
    main()
