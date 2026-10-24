"""Agent messages between the Concierge and the context agents (CONTRACTS.md section 7), as uAgents models.

Response fields are the Context parts (CONTRACTS.md section 1) unchanged: the Concierge reshapes them into Context and
posts the numbers as they came.
"""

from uagents import Model


class WeatherRequest(Model):
    lat: float
    lon: float
    hours: int


class WeatherPoint(Model):
    ts: str
    temp_c: float


class WeatherResponse(Model):
    hourly: list[WeatherPoint]
    source: str
    label: str  # live_api | recorded


class PriceRequest(Model):
    region: str  # e.g. "caiso_np15"
    hours: int


class PricePoint(Model):
    ts: str
    usd_per_kwh: float


class PriceResponse(Model):
    hourly: list[PricePoint]
    stress: str  # low | normal | high
    source: str
    label: str


class EventsRequest(Model):
    lat: float
    lon: float
    radius_km: float
    window_h: int


class EventItem(Model):
    name: str
    venue: str
    start: str
    distance_km: float
    expected_attendance: int


class EventsResponse(Model):
    items: list[EventItem]
    source: str
    label: str
