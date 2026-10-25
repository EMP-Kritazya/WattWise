"""WattWise Grid agent: hourly wholesale electricity prices + a stress level (CAISO OASIS).

PriceRequest {region, hours} → PriceResponse {hourly[{ts, usd_per_kwh}], stress, source "caiso", label}.
Live: CAISO day-ahead LMP (PRC_LMP, DAM) at the region's trading hub, from the current hour. CAISO publishes $/MWh; the
only change is the unit shift to $/kWh (an exact decimal move, no rounding). CAISO slow, blocked or empty → the recorded
fixture, labeled `recorded` (never a live label on recorded numbers). `--recorded` / DEMO_MODE=1: always the fixture.
Chat (Agent Chat Protocol, for any ASI:One user or agent): "price next 3 hours" (NP15 by default; "SP15" / "ZP26" in the
message pick that hub) -> the same answer as plain text with its label.

Run:  python agents/grid.py [--recorded]      (seed: GRID_AGENT_SEED, or derived from FETCH_AGENT_SEED)
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from uagents import Context, Protocol

from common import load_dotenv, load_fixture, make_agent, recorded_mode
from models import PriceRequest, PriceResponse
from public_chat import make_chat_protocol, parse_hours, when

log = logging.getLogger("agents.grid")

OASIS_URL = "https://oasis.caiso.com/oasisapi/SingleZip"
SOURCE = "caiso"
TIMEOUT_S = 8.0
NODES = {"caiso_np15": "TH_NP15_GEN-APND", "caiso_sp15": "TH_SP15_GEN-APND", "caiso_zp26": "TH_ZP26_GEN-APND"}
CHAT_DEFAULT_REGION = "caiso_np15"
CHAT_DEFAULT_HOURS = 6
CHAT_MAX_HOURS = 24

# STUB: stress thresholds on the window's highest LMP ($/MWh). CONTRACTS.md defines `stress` (low | normal | high) but not
# how to derive it from prices; contract question for Kritazya.
STRESS_LOW_BELOW_USD_PER_MWH = Decimal("30")
STRESS_HIGH_FROM_USD_PER_MWH = Decimal("100")


def recorded() -> PriceResponse:
    return PriceResponse.model_validate(load_fixture("price_response.json"))


def stress_for(max_usd_per_mwh: Decimal) -> str:
    if max_usd_per_mwh >= STRESS_HIGH_FROM_USD_PER_MWH:
        return "high"
    if max_usd_per_mwh < STRESS_LOW_BELOW_USD_PER_MWH:
        return "low"
    return "normal"


def from_oasis_zip(content: bytes) -> PriceResponse:
    """OASIS SingleZip (resultformat=6, CSV) → PriceResponse. Raises ValueError when CAISO sent no prices (its errors
    come back as a zip holding an XML file)."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError(f"no CSV in OASIS reply: {z.namelist()}")
        text = z.read(names[0]).decode("utf-8")
    rows = sorted(
        (r for r in csv.DictReader(io.StringIO(text)) if r["LMP_TYPE"] == "LMP"),
        key=lambda r: r["INTERVALSTARTTIME_GMT"],
    )
    if not rows:
        raise ValueError("OASIS reply has no LMP rows")
    prices = [Decimal(r["MW"]) for r in rows]  # the LMP in $/MWh, read as an exact decimal
    hourly = [
        {"ts": r["INTERVALSTARTTIME_GMT"].replace("-00:00", "Z"), "usd_per_kwh": float(p / 1000)}
        for r, p in zip(rows, prices)
    ]
    return PriceResponse.model_validate(
        {"hourly": hourly, "stress": stress_for(max(prices)), "source": SOURCE, "label": "live_api"}
    )


async def fetch_live(req: PriceRequest, client: httpx.AsyncClient, now: datetime | None = None) -> PriceResponse:
    node = NODES.get(req.region)
    if node is None:
        raise ValueError(f"unknown region {req.region!r}; expected one of {sorted(NODES)}")
    start = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=req.hours)
    params = {
        "queryname": "PRC_LMP",
        "market_run_id": "DAM",
        "node": node,
        "startdatetime": start.strftime("%Y%m%dT%H:%M-0000"),
        "enddatetime": end.strftime("%Y%m%dT%H:%M-0000"),
        "version": "12",
        "resultformat": "6",
    }
    r = await client.get(OASIS_URL, params=params, timeout=TIMEOUT_S, follow_redirects=True)
    r.raise_for_status()
    return from_oasis_zip(r.content)


async def answer(req: PriceRequest, *, use_recorded: bool, client: httpx.AsyncClient | None = None,
                 now: datetime | None = None) -> PriceResponse:
    """Always a reply: live CAISO, or the recorded fixture (label `recorded`) when CAISO fails."""
    if use_recorded:
        return recorded()
    try:
        if client is not None:
            return await fetch_live(req, client, now)
        async with httpx.AsyncClient() as own:
            return await fetch_live(req, own, now)
    except (httpx.HTTPError, zipfile.BadZipFile, KeyError, ValueError, ArithmeticError) as e:
        log.warning("CAISO failed (%s); answering with the recorded prices", e)
        return recorded()


proto = Protocol(name="wattwise-grid", version="0.1.0")
RECORDED = False


@proto.on_message(PriceRequest, replies=PriceResponse)
async def on_request(ctx: Context, sender: str, req: PriceRequest):
    await ctx.send(sender, await answer(req, use_recorded=RECORDED))


def parse_region(text: str) -> str:
    """"SP15" / "ZP26" / "NP15" in the message -> that CAISO hub; otherwise NP15."""
    lowered = text.lower()
    for region in NODES:
        if region.removeprefix("caiso_") in lowered:
            return region
    return CHAT_DEFAULT_REGION


def chat_text(region: str, hours: int, reply: PriceResponse) -> str:
    """The reply as plain text: prices exactly as the agent returns them ($/kWh), timestamps in UTC, with the label."""
    rows = reply.hourly[:hours]
    hub = region.removeprefix("caiso_").upper()
    lines = [f"WattWise Grid: CAISO {hub} next {len(rows)} h ({reply.label}, source {reply.source}, day-ahead LMP):"]
    lines += [f"- {when(p.ts)}: {p.usd_per_kwh} $/kWh" for p in rows]
    lines.append(f"Grid stress: {reply.stress}.")
    return "\n".join(lines)


async def answer_text(text: str, client: httpx.AsyncClient | None = None, now: datetime | None = None) -> str:
    region = parse_region(text)
    hours = parse_hours(text, CHAT_DEFAULT_HOURS, CHAT_MAX_HOURS)
    reply = await answer(PriceRequest(region=region, hours=hours), use_recorded=RECORDED, client=client, now=now)
    return chat_text(region, hours, reply)


def main() -> None:
    global RECORDED
    load_dotenv()
    RECORDED = recorded_mode()
    agent = make_agent("grid", "WattWise Grid",
                       "Hourly California (CAISO) wholesale electricity prices and grid stress. Ask in plain text, e.g. "
                       "'price next 3 hours', or send a typed PriceRequest.")
    agent.include(proto, publish_manifest=True)
    agent.include(make_chat_protocol(answer_text), publish_manifest=True)

    @agent.on_event("startup")
    async def announce(ctx: Context):
        ctx.logger.info(f"WattWise Grid address: {agent.address} ({'recorded' if RECORDED else 'live'})")

    agent.run()


if __name__ == "__main__":
    main()
