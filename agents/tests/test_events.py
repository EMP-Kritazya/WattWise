"""Events live mode with the network mocked: Ticketmaster fields pass through unchanged (no attendance, never estimated),
every live failure falls back to the recorded event labeled `recorded` with an error log, and recorded mode never calls
Ticketmaster."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

import events
from models import EventsRequest

SAMPLE = json.loads((Path(__file__).parent / "samples" / "ticketmaster_events.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc)
REQ = EventsRequest(lat=37.8, lon=-122.44, radius_km=4.2, window_h=12)
RECORDED = events.recorded_listing()


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_ticketmaster_sample_maps_unchanged():
    assert events.from_ticketmaster(SAMPLE) == events.EventsListing(
        items=[events.ListedEvent("San Francisco Giants vs. Los Angeles Dodgers", "Oracle Park", "2026-10-25T02:05:00Z",
                                  4.21, None),
               events.ListedEvent("Late Night Jazz", "Black Cat", "2026-10-25T05:30:00Z", 2.6, None)],
        source="ticketmaster", label="live_api")


def test_no_events_is_an_empty_live_listing():
    assert events.from_ticketmaster({"page": {"totalElements": 0}}) == events.EventsListing([], "ticketmaster", "live_api")


async def test_live_request_parameters(monkeypatch):
    monkeypatch.setenv("TICKETMASTER_API_KEY", "test-key")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=SAMPLE)

    reply = await events.listing(REQ, use_recorded=False, client=client(handler), now=NOW)
    assert reply.label == "live_api" and len(reply.items) == 2
    assert str(seen[0].url).startswith(events.TICKETMASTER_URL)
    assert dict(seen[0].url.params) == {
        "apikey": "test-key", "latlong": "37.8,-122.44", "radius": "5", "unit": "km",
        "startDateTime": "2026-10-24T23:30:00Z", "endDateTime": "2026-10-25T11:30:00Z", "sort": "date,asc", "size": "20"}


async def test_no_key_means_recorded(monkeypatch, caplog):
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)

    def handler(request):
        raise AssertionError("no call without a key")

    with caplog.at_level(logging.ERROR, logger="agents.events"):
        assert await events.listing(REQ, use_recorded=False, client=client(handler), now=NOW) == RECORDED
    assert RECORDED.label == "recorded"
    assert "TICKETMASTER_API_KEY" in caplog.text


async def test_rate_limit_means_recorded_with_error_log_and_no_key_in_it(monkeypatch, caplog):
    monkeypatch.setenv("TICKETMASTER_API_KEY", "secret-key")

    def handler(request):
        return httpx.Response(429, json={"fault": {"faultstring": "Rate limit quota violation"}})

    with caplog.at_level(logging.ERROR, logger="agents.events"):
        assert await events.listing(REQ, use_recorded=False, client=client(handler), now=NOW) == RECORDED
    assert [r.levelno for r in caplog.records] == [logging.ERROR]
    assert "429" in caplog.text and "secret-key" not in caplog.text


async def test_timeout_server_error_or_bad_json_means_recorded(monkeypatch, caplog):
    monkeypatch.setenv("TICKETMASTER_API_KEY", "test-key")

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    for handler in (slow, lambda r: httpx.Response(500), lambda r: httpx.Response(200, content=b"not json")):
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="agents.events"):
            assert await events.listing(REQ, use_recorded=False, client=client(handler), now=NOW) == RECORDED
        assert caplog.records


async def test_recorded_mode_never_calls_ticketmaster(monkeypatch):
    monkeypatch.setenv("TICKETMASTER_API_KEY", "test-key")

    def handler(request):
        raise AssertionError("recorded mode must not call Ticketmaster")

    assert await events.listing(REQ, use_recorded=True, client=client(handler)) == RECORDED


async def test_typed_reply_keeps_the_recorded_event_until_attendance_may_be_null():
    assert (await events.answer(REQ, use_recorded=False)).model_dump() == events.recorded().model_dump()


async def test_live_chat_shows_local_and_utc_time_and_no_attendance(monkeypatch):
    monkeypatch.setenv("TICKETMASTER_API_KEY", "test-key")
    monkeypatch.setattr(events, "RECORDED", False)
    seen = []

    async def classify(evts):
        seen.append(evts)
        return {"value": "large", "reason": "Giants game at Oracle Park, 4.21 km"}

    text = await events.answer_text("events tonight", client=client(lambda r: httpx.Response(200, json=SAMPLE)), now=NOW,
                                    classify=classify)
    assert text.splitlines() == [
        "WattWise Events: near Marina, San Francisco, next 12 h (live_api, source ticketmaster):",
        "- San Francisco Giants vs. Los Angeles Dodgers at Oracle Park, 2026-10-24 19:05 PDT (2026-10-25 02:05 UTC), "
        "4.21 km away, attendance not published",
        "- Late Night Jazz at Black Cat, 2026-10-24 22:30 PDT (2026-10-25 05:30 UTC), 2.6 km away, attendance not published",
        "Crowd effect: large (set by claude): Giants game at Oracle Park, 4.21 km",
    ]
    # Claude sees the live events unchanged, attendance null: nothing estimated on the way
    assert seen[0]["items"][0] == {"name": "San Francisco Giants vs. Los Angeles Dodgers", "venue": "Oracle Park",
                                   "start": "2026-10-25T02:05:00Z", "distance_km": 4.21, "expected_attendance": None}


async def test_crowd_not_classified_when_claude_is_off_or_fails():
    live = events.from_ticketmaster(SAMPLE)

    async def fails(evts):
        return None

    for classify in (None, fails):
        assert await events.crowd_line(live, classify) == "Crowd effect: not classified right now (Claude unavailable)."


async def test_recorded_events_get_the_recorded_crowd_effect_not_claude():
    async def claude(evts):
        raise AssertionError("recorded events are not sent to Claude")

    assert await events.crowd_line(RECORDED, claude) == "Crowd effect: medium (recorded): Game ends 22:00, 1.8 km away"


async def test_no_events_means_no_crowd_line(monkeypatch):
    monkeypatch.setenv("TICKETMASTER_API_KEY", "test-key")
    monkeypatch.setattr(events, "RECORDED", False)

    async def classify(evts):
        raise AssertionError("nothing to classify")

    text = await events.answer_text("events tonight", client=client(lambda r: httpx.Response(200, json={})), now=NOW,
                                    classify=classify)
    assert text == "WattWise Events: near Marina, San Francisco, next 12 h (live_api, source ticketmaster): no events found."


def test_missing_fields_say_not_published():
    e = events.ListedEvent("Pop-up", None, None, None, None)
    assert events.event_line(e) == ("- Pop-up at venue not published, start time not published, distance not published, "
                                    "attendance not published")
