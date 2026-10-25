"""Public chat for Weather, Grid and Events: the message is parsed by code, numbers reach the text unchanged with their
label, failures say so, and every chat message is acknowledged before the answer."""

from types import SimpleNamespace

import httpx

import events
import grid
import public_chat
import weather
from common import load_fixture
from public_chat import parse_hours, parse_latlon, parse_place, resolve_location, when
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, EndSessionContent, TextContent

OPEN_METEO = {"hourly": {"time": ["2026-10-24T18:00", "2026-10-24T19:00", "2026-10-24T20:00"],
                         "temperature_2m": [15.3, 16.1, 16.85]}}
GEOCODE = {"results": [{"name": "Berkeley", "country": "United States", "latitude": 37.87159, "longitude": -122.27275}]}


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_hours():
    assert parse_hours("price next 3 hours", 6, 24) == 3
    assert parse_hours("next 12h please", 6, 24) == 12
    assert parse_hours("a 2-hour window", 6, 24) == 2
    assert parse_hours("price now", 6, 24) == 6
    assert parse_hours("next 100 hours", 6, 24) == 24
    assert parse_hours("next 0 hours", 6, 24) == 1


def test_parse_location():
    assert parse_latlon("forecast at 40.71, -74.01 next 6 hours") == (40.71, -74.01)
    assert parse_latlon("at 95, 10") is None
    assert parse_place("weather in Berkeley next 3 hours") == "Berkeley"
    assert parse_place("how hot in New York tonight?") == "New York"
    assert parse_place("temperature in Paris") == "Paris"
    assert parse_place("weather in 3 hours") is None
    assert parse_place("events near me") is None


def test_when_keeps_utc():
    assert when("2026-07-18T01:00:00Z") == "2026-07-18 01:00 UTC"
    assert when("2026-07-18T02:05:00Z") == "2026-07-18 02:05 UTC"
    assert when("not a time") == "not a time"


async def test_resolve_location_falls_back_to_demo_kitchen():
    def down(request):
        return httpx.Response(503)

    assert await resolve_location("weather next 6 hours") == (37.8, -122.44, "Marina, San Francisco")
    lat, lon, place = await resolve_location("weather in Atlantis", client(down))
    assert (lat, lon) == (37.8, -122.44) and "could not find 'Atlantis'" in place


async def test_weather_chat_live(monkeypatch):
    monkeypatch.setattr(weather, "RECORDED", False)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=GEOCODE if "geocoding" in request.url.host else OPEN_METEO)

    text = await weather.answer_text("weather in Berkeley next 3 hours", client(handler))
    assert text == ("WattWise Weather: Berkeley, United States, next 3 h (live_api, source open-meteo):\n"
                    "- 2026-10-24 18:00 UTC: 15.3 °C\n- 2026-10-24 19:00 UTC: 16.1 °C\n- 2026-10-24 20:00 UTC: 16.85 °C")
    forecast = seen[-1].url.params
    assert (forecast["latitude"], forecast["longitude"], forecast["forecast_hours"]) == ("37.87159", "-122.27275", "3")


async def test_weather_chat_says_when_open_meteo_is_down(monkeypatch):
    monkeypatch.setattr(weather, "RECORDED", False)
    text = await weather.answer_text("weather next 6 hours", client(lambda r: httpx.Response(503)))
    assert "Open-Meteo is not answering" in text and "°C" not in text


async def test_weather_chat_recorded(monkeypatch):
    monkeypatch.setattr(weather, "RECORDED", True)
    rows = load_fixture("weather_response.json")["hourly"][:2]
    text = await weather.answer_text("weather next 2 hours")
    assert text.splitlines()[0] == "WattWise Weather: Marina, San Francisco, next 2 h (recorded, source open-meteo):"
    assert text.splitlines()[1:] == [f"- {when(r['ts'])}: {r['temp_c']} °C" for r in rows]


async def test_grid_chat_recorded_matches_fixture(monkeypatch):
    monkeypatch.setattr(grid, "RECORDED", True)
    fixture = load_fixture("price_response.json")
    text = await grid.answer_text("price next 3 hours")
    lines = text.splitlines()
    assert lines[0] == "WattWise Grid: CAISO NP15 next 3 h (recorded, source caiso, day-ahead LMP):"
    assert lines[1:4] == [f"- {when(p['ts'])}: {p['usd_per_kwh']} $/kWh" for p in fixture["hourly"][:3]]
    assert lines[4] == f"Grid stress: {fixture['stress']}."


async def test_grid_chat_caiso_down_is_labeled_recorded(monkeypatch):
    monkeypatch.setattr(grid, "RECORDED", False)
    text = await grid.answer_text("SP15 price next 2 hours", client(lambda r: httpx.Response(503)))
    assert text.startswith("WattWise Grid: CAISO SP15 next 2 h (recorded, source caiso")
    assert "live_api" not in text


def test_parse_region():
    assert grid.parse_region("price next 3 hours") == "caiso_np15"
    assert grid.parse_region("SP15 price") == "caiso_sp15"
    assert grid.parse_region("zp26 now") == "caiso_zp26"


async def test_events_chat_recorded(monkeypatch):
    monkeypatch.setattr(events, "RECORDED", False)
    item = load_fixture("events_response.json")["items"][0]
    text = await events.answer_text("events tonight")
    assert text.splitlines() == [
        "WattWise Events: near Marina, San Francisco, next 12 h (recorded, source demo_events):",
        f"- {item['name']} at {item['venue']}, {when(item['start'])}, {item['distance_km']} km away, "
        f"expected attendance {item['expected_attendance']}",
    ]


class FakeCtx:
    def __init__(self):
        self.sent = []
        self.logger = SimpleNamespace(info=lambda *a: None, debug=lambda *a: None)

    async def send(self, to, msg):
        self.sent.append((to, msg))


def chat_handler(proto):
    # uAgents has no public handler lookup; chat messages are signed.
    return next(h for h in proto._signed_message_handlers.values() if h.__name__ == "on_chat")


async def test_chat_protocol_acks_then_answers():
    async def answer_text(text):
        return f"echo: {text}"

    on_chat = chat_handler(public_chat.make_chat_protocol(answer_text))
    ctx = FakeCtx()
    msg = public_chat.text_message("price next 3 hours")
    await on_chat(ctx, "agent1user", msg)
    (to1, ack), (to2, reply) = ctx.sent
    assert to1 == to2 == "agent1user"
    assert isinstance(ack, ChatAcknowledgement) and ack.acknowledged_msg_id == msg.msg_id
    assert isinstance(reply, ChatMessage) and reply.content == [TextContent(type="text", text="echo: price next 3 hours")]


async def test_chat_protocol_session_markers_only_acked():
    async def answer_text(text):
        raise AssertionError("no question to answer")

    on_chat = chat_handler(public_chat.make_chat_protocol(answer_text))
    ctx = FakeCtx()
    msg = ChatMessage(timestamp=public_chat.datetime.now(public_chat.timezone.utc), msg_id=public_chat.uuid4(),
                      content=[EndSessionContent(type="end-session")])
    await on_chat(ctx, "agent1user", msg)
    assert len(ctx.sent) == 1 and isinstance(ctx.sent[0][1], ChatAcknowledgement)
