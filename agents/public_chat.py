"""Agent Chat Protocol for the public context agents (Weather, Grid, Events), so any ASI:One user or agent can ask them in
plain text next to their typed protocols.

Each agent supplies `answer_text(text) -> str`: it reads what it needs from the message (hours, place, region), asks its
own live source through its typed `answer()`, and writes the numbers unchanged with their label (`live_api` / `recorded`).
Every message is acknowledged; session start / end markers carry no text and get only the acknowledgement.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

log = logging.getLogger("agents.public_chat")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
GEOCODE_TIMEOUT_S = 5.0

# The demo kitchen's location (contracts/fixtures/scenario/demo_cafe/scenario.json), used when the message names no place.
DEFAULT_LAT = 37.8
DEFAULT_LON = -122.44
DEFAULT_PLACE = "Marina, San Francisco"

_HOURS = re.compile(r"(\d{1,3})\s*-?\s*(?:h|hr|hrs|hour|hours)\b", re.IGNORECASE)
_LATLON = re.compile(r"(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)")
_PLACE = re.compile(r"\b(?:in|at|near|around)\s+([A-Za-z][A-Za-z .'-]*?)\s*(?=\b(?:next|for|over|today|tonight|tomorrow"
                    r"|this|within)\b|[?.!,;]|$)", re.IGNORECASE)
_NOT_PLACES = {"me", "here", "my area", "my restaurant", "my kitchen", "the area", "the city"}


def parse_hours(text: str, default: int, maximum: int) -> int:
    """"next 3 hours" / "12h" → 3 / 12, clamped to 1..maximum; no hours in the text → default."""
    m = _HOURS.search(text)
    return default if m is None else max(1, min(int(m.group(1)), maximum))


def parse_latlon(text: str) -> tuple[float, float] | None:
    """"37.8, -122.44" → (37.8, -122.44) when both are valid coordinates."""
    m = _LATLON.search(text)
    if m is None:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def parse_place(text: str) -> str | None:
    """"weather in Berkeley next 6 hours" → "Berkeley"."""
    m = _PLACE.search(text)
    place = m.group(1).strip(" .'-") if m else ""
    return place if place and place.lower() not in _NOT_PLACES else None


async def geocode(place: str, client: httpx.AsyncClient | None = None) -> tuple[float, float, str] | None:
    """Open-Meteo geocoding: a place name → (lat, lon, "Name, Country"), or None (not found or the service failed)."""
    try:
        if client is not None:
            r = await client.get(GEOCODE_URL, params={"name": place, "count": 1}, timeout=GEOCODE_TIMEOUT_S)
        else:
            async with httpx.AsyncClient() as own:
                r = await own.get(GEOCODE_URL, params={"name": place, "count": 1}, timeout=GEOCODE_TIMEOUT_S)
        r.raise_for_status()
        hit = (r.json().get("results") or [None])[0]
        if not hit:
            return None
        label = ", ".join(p for p in (hit.get("name"), hit.get("country")) if p)
        return float(hit["latitude"]), float(hit["longitude"]), label
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        log.warning("geocoding %r failed (%s)", place, e)
        return None


async def resolve_location(text: str, client: httpx.AsyncClient | None = None) -> tuple[float, float, str]:
    """Coordinates in the text, else a named place, else the demo kitchen's location; the label says which."""
    coords = parse_latlon(text)
    if coords is not None:
        return coords[0], coords[1], f"{coords[0]}, {coords[1]}"
    place = parse_place(text)
    if place is not None:
        found = await geocode(place, client)
        if found is not None:
            return found
        return DEFAULT_LAT, DEFAULT_LON, f"{DEFAULT_PLACE} (could not find {place!r})"
    return DEFAULT_LAT, DEFAULT_LON, DEFAULT_PLACE


def when(ts: str) -> str:
    """"2026-07-18T01:00:00Z" → "2026-07-18 01:00 UTC" (timestamps stay UTC; no conversion)."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return ts


def text_message(text: str) -> ChatMessage:
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=[TextContent(type="text", text=text)])


def message_text(msg: ChatMessage) -> str:
    return " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()


def make_chat_protocol(answer_text: Callable[[str], Awaitable[str]]) -> Protocol:
    """The Agent Chat Protocol: acknowledge, then reply with `answer_text(question)` as one text message."""
    proto = Protocol(spec=chat_protocol_spec)

    @proto.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        text = message_text(msg)
        if not text:
            return
        ctx.logger.info(f"chat from {sender}: {text!r}")
        await ctx.send(sender, text_message(await answer_text(text)))

    @proto.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")

    return proto
