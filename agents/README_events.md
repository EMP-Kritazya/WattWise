![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# WattWise Events: nearby events and crowd agent

**Agent:** WattWise Events | `@wattwiseevents` | `agent1qfpewxv737laxv5gk0zcraucrdse4cwl596399ce5cruy5kmn3t3v5h262y`

Events near a restaurant in the next hours, with venue, start time and distance (Ticketmaster Discovery API).

Big events nearby (a ballgame, a concert) bring a crowd into nearby restaurants. This agent lists them so a kitchen, or
any agent, can plan for the rush. Every answer carries its label: live events come from Ticketmaster (source
`ticketmaster`, label `live_api`), fields passed through unchanged. If Ticketmaster is unavailable (no key, timeout, HTTP
error, rate limit) the agent answers with recorded demo data for San Francisco (source `demo_events`, label `recorded`).
Demo mode (`--recorded` / `DEMO_MODE=1`) always uses the recorded data.

## Ask in plain text (ASI:One, Agent Chat Protocol)

```
Input:  @wattwiseevents events tonight
Output: WattWise Events: near Marina, San Francisco, next 12 h (live_api, source ticketmaster):
        - San Francisco Giants vs. Los Angeles Dodgers at Oracle Park, 2026-10-24 19:05 PDT (2026-10-25 02:05 UTC),
          4.21 km away, attendance not published
        ...
        Crowd effect: medium (set by claude): <Claude's short reason, quoting the event data>
```

Example prompts:

- events tonight
- any big events nearby in the next 6 hours?
- will a game bring a crowd this evening?
- concerts or games near the restaurant next 24 hours

Hours: 1 to 24 (default 12). Start times in local time (America/Los_Angeles) with UTC next to them.

The last line is the crowd effect: how much these events should raise a nearby restaurant's traffic, as a category
(`none`, `small`, `medium`, `large`). Claude picks it from the event list (structured output, an enum); it is never an
attendance number. Recorded events get the recorded crowd effect. Without `ANTHROPIC_API_KEY`, or if Claude fails, the
line says "not classified".

## Call it from your agent (typed messages, uAgents)

Protocol `wattwise-events` 0.1.0 (manifest published). Send an `EventsRequest`, receive an `EventsResponse`:

```python
from uagents import Model

class EventsRequest(Model):
    lat: float
    lon: float
    radius_km: float
    window_h: int

class EventItem(Model):
    name: str
    venue: str
    start: str               # ISO 8601 UTC
    distance_km: float
    expected_attendance: int

class EventsResponse(Model):
    items: list[EventItem]
    source: str  # "demo_events"
    label: str   # recorded
```

```python
reply, status = await ctx.send_and_receive(EVENTS_ADDRESS,
                                           EventsRequest(lat=37.8, lon=-122.44, radius_km=5, window_h=12),
                                           response_type=EventsResponse, timeout=15)
```

## Limitations

- No attendance: Ticketmaster does not publish it, and the agent never estimates it (chat says "attendance not
  published"). The crowd effect category stands in for it.
- Typed `EventsResponse` replies are still the recorded event (label `recorded`): the contract requires
  `expected_attendance` as a number, which Ticketmaster does not give. Live events reach chat replies only, for now.
- Chat looks up events near the demo location (Marina, San Francisco) only; a place named in the message is not used yet.
- Live mode needs `TICKETMASTER_API_KEY`; Ticketmaster's free tier is rate limited (a 429 falls back to recorded).

## Metadata

WattWise team, Cal Hacks 13.0, Fetch.ai Innovation Lab. Version 0.1. Part of WattWise, which keeps a restaurant's
electricity peak under its owner's cap; the WattWise Concierge (@wattwise) uses this agent to judge the crowd effect.
Keywords: events nearby, local events, Ticketmaster, crowd, ballgame, concert, restaurant rush, foot traffic.
