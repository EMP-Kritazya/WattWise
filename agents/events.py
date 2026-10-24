"""WattWise Events agent (tier 2): events near the kitchen in the next hours, with expected attendance.

EventsRequest {lat, lon, radius_km, window_h} → EventsResponse {items[...], source, label}.
Only the recorded answer exists so far (one recorded sports event, source `demo_events`, label `recorded`).

Run:  python agents/events.py [--recorded]      (seed: EVENTS_AGENT_SEED, or derived from FETCH_AGENT_SEED)
"""

from __future__ import annotations

import logging

from uagents import Context, Protocol

from common import load_dotenv, load_fixture, make_agent, recorded_mode
from models import EventsRequest, EventsResponse

log = logging.getLogger("agents.events")


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


def main() -> None:
    global RECORDED
    load_dotenv()
    RECORDED = recorded_mode()
    agent = make_agent("events", "WattWise Events",
                       "Events near a restaurant in the next hours with expected attendance, for WattWise.")
    agent.include(proto, publish_manifest=True)

    @agent.on_event("startup")
    async def announce(ctx: Context):
        ctx.logger.info(f"WattWise Events address: {agent.address} ({'recorded' if RECORDED else 'live'})")

    agent.run()


if __name__ == "__main__":
    main()
