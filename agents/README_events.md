![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# WattWise Events: nearby events and crowd agent

**Agent:** WattWise Events | `@wattwiseevents` | `agent1qfpewxv737laxv5gk0zcraucrdse4cwl596399ce5cruy5kmn3t3v5h262y`

Events near a restaurant in the next hours, with venue, start time, distance and expected attendance.

Big events nearby (a ballgame, a concert) bring a crowd into nearby restaurants. This agent lists them so a kitchen, or
any agent, can plan for the rush. Every answer carries its label. Today the agent answers from recorded demo data for
San Francisco (source `demo_events`, label `recorded`); no live events provider is connected yet.

## Ask in plain text (ASI:One, Agent Chat Protocol)

```
Input:  @wattwiseevents events tonight
Output: WattWise Events: near Marina, San Francisco, next 12 h (recorded, source demo_events):
        - Giants vs Dodgers at Oracle Park, 2026-07-18 02:05 UTC, 1.8 km away, expected attendance 40000
```

Example prompts:

- events tonight
- any big events nearby in the next 6 hours?
- will a game bring a crowd this evening?
- concerts or games near the restaurant next 24 hours

Hours: 1 to 24 (default 12). Times are UTC.

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
    label: str   # recorded (live_api once a live provider is connected)
```

```python
reply, status = await ctx.send_and_receive(EVENTS_ADDRESS,
                                           EventsRequest(lat=37.8, lon=-122.44, radius_km=5, window_h=12),
                                           response_type=EventsResponse, timeout=15)
```

## Limitations

- Recorded demo data only (one San Francisco event), whatever the location asked; labeled `recorded` every time.

## Metadata

WattWise team, Cal Hacks 13.0, Fetch.ai Innovation Lab. Version 0.1. Part of WattWise, which keeps a restaurant's
electricity peak under its owner's cap; the WattWise Concierge (@wattwise) uses this agent to judge the crowd effect.
Keywords: events nearby, local events, crowd, ballgame, concert, expected attendance, restaurant rush, foot traffic.
