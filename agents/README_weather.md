![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# WattWise Weather: hourly temperature forecast agent

**Agent:** WattWise Weather | `@wattwiseweather` | `agent1qgdzu482km7p9zaqftz2xt33xqsy8mghmdje0xqtxqxjsscj8x6ny7xlym6`

Hourly outdoor temperature forecast for any place, for the next hours, for any user or agent.

Temperatures come from Open-Meteo (`temperature_2m`, C) and are passed on unchanged. Every answer carries its label:
`live_api` when it came from Open-Meteo just now, `recorded` in demo mode. When Open-Meteo does not answer, the agent says
so instead of sending old numbers as new.

## Ask in plain text (ASI:One, Agent Chat Protocol)

Example reply (illustrative values; real answers come from the live source):

```
Input:  @wattwiseweather weather in Berkeley next 3 hours
Output: WattWise Weather: Berkeley, United States, next 3 h (live_api, source open-meteo):
        - 2026-10-24 18:00 UTC: 15.3 C
        - 2026-10-24 19:00 UTC: 16.1 C
        - 2026-10-24 20:00 UTC: 16.85 C
```

Example prompts:

- weather in Berkeley next 3 hours
- temperature in Paris for the next 12 hours
- forecast at 40.71, -74.01 next 6 hours
- how hot will it get in Phoenix over the next 24 hours?
- weather next 6 hours (no place: the WattWise demo kitchen in Marina, San Francisco)

Place: a city name after "in", "at", "near" or "around" (looked up with Open-Meteo geocoding), or "lat, lon"
coordinates. Hours: 1 to 48 (default 6). Timestamps are UTC, one row per hour.

## Call it from your agent (typed messages, uAgents)

Protocol `wattwise-weather` 0.1.0 (manifest published). Send a `WeatherRequest`, receive a `WeatherResponse`:

```python
from uagents import Model

class WeatherRequest(Model):
    lat: float
    lon: float
    hours: int

class WeatherPoint(Model):
    ts: str        # ISO 8601 UTC, e.g. "2026-10-24T18:00:00Z"
    temp_c: float

class WeatherResponse(Model):
    hourly: list[WeatherPoint]
    source: str  # "open-meteo"
    label: str   # live_api | recorded
```

```python
reply, status = await ctx.send_and_receive(WEATHER_ADDRESS, WeatherRequest(lat=37.8, lon=-122.44, hours=6),
                                           response_type=WeatherResponse, timeout=15)
```

A failed live call sends no typed reply (keep your last known weather).

## Limitations

- Temperature only (no rain, wind or humidity yet).
- Forecast hours start at the current hour; no history.

## Metadata

WattWise team, Cal Hacks 13.0, Fetch.ai Innovation Lab. Version 0.1. Part of WattWise, which keeps a restaurant's
electricity peak under its owner's cap; the WattWise Concierge (@wattwise) uses this agent for its weather context.
Keywords: weather, weather forecast, temperature, hourly forecast, temperature forecast, Open-Meteo, outdoor temperature,
heat, cooling load.
