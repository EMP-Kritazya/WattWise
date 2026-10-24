"""WattWise Weather agent: hourly outdoor temperature for the kitchen's location (Open-Meteo).

WeatherRequest {lat, lon, hours} → WeatherResponse {hourly[{ts, temp_c}], source "open-meteo", label}.
Live: Open-Meteo's `temperature_2m` in UTC, numbers unchanged (only the timestamps are written as `...Z`), label
`live_api`. `--recorded` / DEMO_MODE=1: the recorded fixture, label `recorded`. A failed live call sends no reply: the
Concierge then keeps the last known weather.

Run:  python agents/weather.py [--recorded]      (seed: WEATHER_AGENT_SEED, or derived from FETCH_AGENT_SEED)
"""

from __future__ import annotations

import logging

import httpx
from uagents import Context, Protocol

from common import load_dotenv, load_fixture, make_agent, recorded_mode
from models import WeatherRequest, WeatherResponse

log = logging.getLogger("agents.weather")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE = "open-meteo"
TIMEOUT_S = 8.0


def recorded() -> WeatherResponse:
    return WeatherResponse.model_validate(load_fixture("weather_response.json"))


def from_open_meteo(payload: dict) -> WeatherResponse:
    """Open-Meteo hourly JSON (timezone GMT) → WeatherResponse. Temperatures pass through unchanged."""
    hourly = payload["hourly"]
    rows = [
        {"ts": f"{t}:00Z", "temp_c": temp}  # "2026-07-18T01:00" (UTC) → "2026-07-18T01:00:00Z"
        for t, temp in zip(hourly["time"], hourly["temperature_2m"])
        if temp is not None
    ]
    return WeatherResponse.model_validate({"hourly": rows, "source": SOURCE, "label": "live_api"})


async def fetch_live(req: WeatherRequest, client: httpx.AsyncClient) -> WeatherResponse:
    params = {
        "latitude": req.lat,
        "longitude": req.lon,
        "hourly": "temperature_2m",
        "temperature_unit": "celsius",
        "timezone": "GMT",
        "forecast_hours": req.hours,
    }
    r = await client.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT_S)
    r.raise_for_status()
    return from_open_meteo(r.json())


async def answer(req: WeatherRequest, *, use_recorded: bool, client: httpx.AsyncClient | None = None
                 ) -> WeatherResponse | None:
    """The reply to one request, or None (live call failed: no reply, the Concierge keeps the last known)."""
    if use_recorded:
        return recorded()
    try:
        if client is not None:
            return await fetch_live(req, client)
        async with httpx.AsyncClient() as own:
            return await fetch_live(req, own)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        log.warning("Open-Meteo failed (%s); no reply", e)
        return None


proto = Protocol(name="wattwise-weather", version="0.1.0")
RECORDED = False


@proto.on_message(WeatherRequest, replies=WeatherResponse)
async def on_request(ctx: Context, sender: str, req: WeatherRequest):
    reply = await answer(req, use_recorded=RECORDED)
    if reply is None:
        ctx.logger.warning(f"no weather for {sender}: live call failed")
        return
    await ctx.send(sender, reply)


def main() -> None:
    global RECORDED
    load_dotenv()
    RECORDED = recorded_mode()
    agent = make_agent("weather", "WattWise Weather",
                       "Hourly outdoor temperature for a restaurant's location (Open-Meteo), for WattWise.")
    agent.include(proto, publish_manifest=True)

    @agent.on_event("startup")
    async def announce(ctx: Context):
        ctx.logger.info(f"WattWise Weather address: {agent.address} ({'recorded' if RECORDED else 'live'})")

    agent.run()


if __name__ == "__main__":
    main()
