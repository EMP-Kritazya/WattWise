![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# WattWise Grid: California wholesale electricity price agent

**Agent:** WattWise Grid | `@wattwisegrid` | `agent1qvnts5cnkals04rcfesxwhhcs35d50025vyw4j5539d0fg0t2jwpqzunfkt`

Hourly California (CAISO) wholesale electricity prices for the next hours, with a grid stress level, for any user or agent.

Prices are CAISO's day-ahead locational marginal price (LMP) at a trading hub (NP15 by default, SP15 or ZP26 on request),
read from CAISO OASIS and passed on unchanged apart from the unit shift from $/MWh to $/kWh. Every answer carries its
label: `live_api` when it came from CAISO just now, `recorded` when CAISO was slow or unavailable and the agent answered
from its recorded prices. Recorded numbers are never labeled live.

## Ask in plain text (ASI:One, Agent Chat Protocol)

Example reply (illustrative values; real answers come from the live source):

```
Input:  @wattwisegrid price next 3 hours
Output: WattWise Grid: CAISO NP15 next 3 h (live_api, source caiso, day-ahead LMP):
        - 2026-10-24 18:00 UTC: 0.04512 $/kWh
        - 2026-10-24 19:00 UTC: 0.0523 $/kWh
        - 2026-10-24 20:00 UTC: 0.06118 $/kWh
        Grid stress: normal.
```

Example prompts:

- price next 3 hours
- electricity price for the next 12 hours
- SP15 wholesale price next 6 hours
- is the California grid stressed right now?
- when is power cheapest in the next 24 hours?

Hours: 1 to 24 (default 6). Hub: say NP15, SP15 or ZP26 (default NP15). Timestamps are UTC, one row per hour.

## Call it from your agent (typed messages, uAgents)

Protocol `wattwise-grid` 0.1.0 (manifest published). Send a `PriceRequest`, receive a `PriceResponse`:

```python
from uagents import Model

class PriceRequest(Model):
    region: str  # "caiso_np15" | "caiso_sp15" | "caiso_zp26"
    hours: int

class PricePoint(Model):
    ts: str            # ISO 8601 UTC, e.g. "2026-10-24T18:00:00Z"
    usd_per_kwh: float

class PriceResponse(Model):
    hourly: list[PricePoint]
    stress: str  # low | normal | high
    source: str  # "caiso"
    label: str   # live_api | recorded
```

```python
reply, status = await ctx.send_and_receive(GRID_ADDRESS, PriceRequest(region="caiso_np15", hours=6),
                                           response_type=PriceResponse, timeout=15)
```

The agent always replies: live CAISO, or the recorded prices labeled `recorded`.

## Limitations

- California only (CAISO trading hubs). Wholesale day-ahead prices, not a retail utility tariff.
- `stress` is a coarse category from the highest price in the window (below $30/MWh low, from $100/MWh high).

## Metadata

WattWise team, Cal Hacks 13.0, Fetch.ai Innovation Lab. Version 0.1. Part of WattWise, which keeps a restaurant's
electricity peak under its owner's cap; the WattWise Concierge (@wattwise) uses this agent for its price context.
Keywords: electricity price, wholesale electricity price, CAISO, California grid, LMP, day-ahead price, NP15, SP15,
grid stress, power price forecast, energy price.
