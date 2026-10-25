"""WattWise Events agent (tier 2): events near the kitchen in the next hours, with expected attendance.

EventsRequest {lat, lon, radius_km, window_h} → EventsResponse {items[...], source, label}.
Only the recorded answer exists so far (one recorded sports event, source `demo_events`, label `recorded`).
Chat (Agent Chat Protocol, for any ASI:One user or agent): "events tonight" -> the same answer as plain text with its label.

Run:  python agents/events.py [--recorded]      (seed: EVENTS_AGENT_SEED, or derived from FETCH_AGENT_SEED)
"""

from __future__ import annotations

import logging

from uagents import Context, Protocol

from common import load_dotenv, load_fixture, make_agent, recorded_mode
from models import EventsRequest, EventsResponse
from public_chat import DEFAULT_LAT, DEFAULT_LON, DEFAULT_PLACE, make_chat_protocol, parse_hours, when

log = logging.getLogger("agents.events")

CHAT_RADIUS_KM = 5.0
CHAT_DEFAULT_HOURS = 12
CHAT_MAX_HOURS = 24


def recorded() -> EventsResponse:
    return EventsResponse.model_validate(load_fixture("events_response.json"))


async def answer(req: EventsRequest, *, use_recorded: bool) -> EventsResponse:
    if not use_recorded:
        # STUB: no live events provider chosen yet (tier 2). Live mode answers with the recorded event, labeled `recorded`.
        log.info("no live events provider yet; answering with the recorded event")
    return recorded()


proto = Protocol(name="wattwise-events", version="0.1.0")
RECORDED = False


@proto.on_message(EventsRequest, replies=EventsResponse)
async def on_request(ctx: Context, sender: str, req: EventsRequest):
    await ctx.send(sender, await answer(req, use_recorded=RECORDED))


def chat_text(hours: int, reply: EventsResponse) -> str:
    """The reply as plain text: every event as the source gave it, start in UTC, with the label."""
    head = f"WattWise Events: near {DEFAULT_PLACE}, next {hours} h ({reply.label}, source {reply.source})"
    if not reply.items:
        return head + ": no events found."
    lines = [head + ":"]
    lines += [f"- {e.name} at {e.venue}, {when(e.start)}, {e.distance_km} km away, expected attendance "
              f"{e.expected_attendance}" for e in reply.items]
    return "\n".join(lines)


async def answer_text(text: str) -> str:
    # STUB: the recorded answer covers the demo kitchen only, so chat always asks for the demo location (a place in the
    # message is not looked up until a live events provider exists).
    hours = parse_hours(text, CHAT_DEFAULT_HOURS, CHAT_MAX_HOURS)
    req = EventsRequest(lat=DEFAULT_LAT, lon=DEFAULT_LON, radius_km=CHAT_RADIUS_KM, window_h=hours)
    return chat_text(hours, await answer(req, use_recorded=RECORDED))


def main() -> None:
    global RECORDED
    load_dotenv()
    RECORDED = recorded_mode()
    agent = make_agent("events", "WattWise Events",
                       "Events near a restaurant in the next hours with expected attendance (recorded demo data for San "
                       "Francisco). Ask in plain text, e.g. 'events tonight', or send a typed EventsRequest.")
    agent.include(proto, publish_manifest=True)
    agent.include(make_chat_protocol(answer_text), publish_manifest=True)

    @agent.on_event("startup")
    async def announce(ctx: Context):
        ctx.logger.info(f"WattWise Events address: {agent.address} ({'recorded' if RECORDED else 'live'})")

    agent.run()


if __name__ == "__main__":
    main()
