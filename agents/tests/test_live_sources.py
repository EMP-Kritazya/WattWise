"""Live mode with the network mocked: Open-Meteo and CAISO numbers pass through unchanged, CAISO failures fall back to
the recorded prices labeled `recorded`, and the Claude crowd call only ever yields a category."""

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

import crowd
import grid
import weather
from common import load_fixture
from models import PriceRequest, WeatherRequest

OPEN_METEO = {
    "latitude": 37.8, "longitude": -122.44,
    "hourly_units": {"time": "iso8601", "temperature_2m": "°C"},
    "hourly": {"time": ["2026-10-24T18:00", "2026-10-24T19:00", "2026-10-24T20:00"],
               "temperature_2m": [15.3, 16.1, 16.85]},
}


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_open_meteo_numbers_pass_unchanged():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=OPEN_METEO)

    reply = await weather.answer(WeatherRequest(lat=37.8, lon=-122.44, hours=3), use_recorded=False,
                                 client=client(handler))
    assert reply.model_dump() == {
        "hourly": [{"ts": "2026-10-24T18:00:00Z", "temp_c": 15.3}, {"ts": "2026-10-24T19:00:00Z", "temp_c": 16.1},
                   {"ts": "2026-10-24T20:00:00Z", "temp_c": 16.85}],
        "source": "open-meteo", "label": "live_api"}
    params = seen[0].url.params
    assert (params["latitude"], params["longitude"], params["forecast_hours"], params["timezone"]) == \
        ("37.8", "-122.44", "3", "GMT")


async def test_open_meteo_down_means_no_reply():
    def handler(request):
        return httpx.Response(503)

    assert await weather.answer(WeatherRequest(lat=1, lon=2, hours=6), use_recorded=False, client=client(handler)) is None


def oasis_zip(rows: list[tuple[str, str, str]]) -> bytes:
    """(interval start GMT, LMP_TYPE, MW) rows as an OASIS SingleZip CSV."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["INTERVALSTARTTIME_GMT", "INTERVALENDTIME_GMT", "NODE", "LMP_TYPE", "MW"])
    for start, kind, mw in rows:
        w.writerow([start, "", "TH_NP15_GEN-APND", kind, mw])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("20261024_20261024_PRC_LMP_DAM_v12.csv", out.getvalue())
    return buf.getvalue()


async def test_caiso_prices_shift_units_exactly_and_sort_by_hour():
    content = oasis_zip([
        ("2026-10-24T19:00:00-00:00", "LMP", "20.9896"),
        ("2026-10-24T18:00:00-00:00", "LMP", "26.40756"),
        ("2026-10-24T18:00:00-00:00", "MCC", "6.30769"),  # a component, not the price
        ("2026-10-24T20:00:00-00:00", "LMP", "112.5"),
    ])
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=content)

    reply = await grid.answer(PriceRequest(region="caiso_np15", hours=3), use_recorded=False, client=client(handler),
                              now=datetime(2026, 10, 24, 18, 25, tzinfo=timezone.utc))
    assert reply.model_dump() == {
        "hourly": [{"ts": "2026-10-24T18:00:00Z", "usd_per_kwh": 0.02640756},
                   {"ts": "2026-10-24T19:00:00Z", "usd_per_kwh": 0.0209896},
                   {"ts": "2026-10-24T20:00:00Z", "usd_per_kwh": 0.1125}],
        "stress": "high", "source": "caiso", "label": "live_api"}
    params = seen[0].url.params
    assert (params["node"], params["startdatetime"], params["enddatetime"]) == \
        ("TH_NP15_GEN-APND", "20261024T18:00-0000", "20261024T21:00-0000")


def test_stress_levels():
    assert [grid.stress_for(grid.Decimal(p)) for p in ("12", "30", "99.99", "100")] == ["low", "normal", "normal", "high"]


async def test_caiso_blocked_or_erroring_falls_back_to_recorded_prices():
    recorded = load_fixture("price_response.json")

    def refused(request):
        raise httpx.ConnectError("blocked", request=request)

    def error_zip(request):  # CAISO reports errors as a zip with an XML file
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("INVALID_REQUEST.xml", "<error/>")
        return httpx.Response(200, content=buf.getvalue())

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    for handler in (refused, error_zip, slow, lambda r: httpx.Response(200, content=b"not a zip")):
        reply = await grid.answer(PriceRequest(region="caiso_np15", hours=6), use_recorded=False,
                                  client=client(handler))
        assert reply.model_dump() == recorded
        assert reply.label == "recorded"


class FakeMessages:
    def __init__(self, message):
        self.message, self.calls = message, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.message, Exception):
            raise self.message
        return self.message


def fake_claude(message) -> tuple[crowd.ClaudeClassifier, FakeMessages]:
    messages = FakeMessages(message)
    return crowd.ClaudeClassifier(SimpleNamespace(beta=SimpleNamespace(messages=messages)), "claude-opus-5-5"), messages


def text_message(text, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


EVENTS = load_fixture("events_response.json")


async def test_claude_crowd_effect_is_a_category_from_an_enum_schema():
    classify, messages = fake_claude(text_message(json.dumps({"value": "medium", "reason": "Giants vs Dodgers, 1.8 km"})))
    assert await classify(EVENTS) == {"value": "medium", "reason": "Giants vs Dodgers, 1.8 km"}
    schema = messages.calls[0]["output_config"]["format"]["schema"]
    assert schema["properties"]["value"]["enum"] == ["none", "small", "medium", "large"]
    assert "Giants vs Dodgers" in messages.calls[0]["messages"][0]["content"]


async def test_claude_refusal_bad_answer_or_error_gives_no_crowd_effect():
    for message in (text_message("", stop_reason="refusal"),
                    text_message(json.dumps({"value": 1.25, "reason": "x"})),
                    text_message("not json"),
                    RuntimeError("overloaded")):
        classify, _ = fake_claude(message)
        assert await classify(EVENTS) is None


def test_no_api_key_means_claude_off(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert crowd.create_classifier(use_recorded=False) is None
    assert crowd.create_classifier(use_recorded=True) is crowd.recorded_classifier
