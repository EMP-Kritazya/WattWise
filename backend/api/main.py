"""FastAPI app: every REST endpoint of CONTRACTS.md §2, `/api/health`, the viewer socket `/ws` and the hub socket `/ws/hub` (§8).

Thin layer: validate the body → call the service → return. Run from backend/: `uvicorn api.main:app`.
"""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from pydantic import BaseModel

from agent.claude_agent import ClaudeAgent, create_llm
from agent.proposals import ProposalBook
from agent.tools import AgentTools
from runtime.device_bridge import DeviceBridge
from runtime.hub_link import HubLink
from runtime.kitchen_factory import load_engine
from runtime.live_port import LivePublisher, WsLive, create_live
from runtime.loop import RunLoop
from store import create_store

from . import models as m
from .errors import install_error_handlers
from .service import KitchenService, seed_fake_scenario
from .settings import Settings
from .ws import Broadcaster

_ERR = {"model": m.ErrorDetail}
R404 = {404: _ERR}


def _body(model: BaseModel) -> dict[str, Any]:
    """The request body as the client sent it (unset optional fields stay absent)."""
    return model.model_dump(mode="json", by_alias=True, exclude_unset=True)


def _service(request: Request) -> KitchenService:
    return request.app.state.service


def _require_agent_token(request: Request, x_agent_token: Annotated[str | None, Header()] = None) -> None:
    expected = request.app.state.settings.agent_token
    if not expected or not x_agent_token or not secrets.compare_digest(x_agent_token, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Agent-Token")


def _runtime(request: Request) -> RunLoop:
    return request.app.state.runtime


def _proposals(request: Request) -> ProposalBook:
    return request.app.state.proposals


def _agent(request: Request) -> ClaudeAgent:
    return request.app.state.agent


Service = Annotated[KitchenService, Depends(_service)]
Runtime = Annotated[RunLoop, Depends(_runtime)]
Proposals = Annotated[ProposalBook, Depends(_proposals)]
Agent = Annotated[ClaudeAgent, Depends(_agent)]
AgentOnly = [Depends(_require_agent_token)]

router = APIRouter(
    prefix="/api",
    # Every error body is { "detail": "text" }. 501 = STUB: no recorded fixture answer yet.
    responses={422: _ERR, 501: _ERR},
)
_exclude_unset = {"response_model_exclude_unset": True}


# ---------------------------------------------------------------- kitchen

@router.get("/catalog", response_model=list[m.EquipmentType], **_exclude_unset)
def get_catalog(svc: Service):
    return svc.catalog()


@router.post("/kitchen", response_model=m.KitchenCreated, **_exclude_unset)
async def post_kitchen(config: m.KitchenConfig, rt: Runtime):
    return await rt.build(_body(config))


@router.get("/kitchen", response_model=m.KitchenView, **_exclude_unset)
def get_kitchen(svc: Service):
    return svc.get_kitchen()


@router.put("/kitchen/devices/{device_id}/importance", response_model=m.Device, responses=R404, **_exclude_unset)
def put_device_importance(device_id: str, body: m.ImportanceUpdate, svc: Service):
    return svc.set_importance(device_id, _body(body))


@router.put("/kitchen/peak-cap", response_model=m.Meter, **_exclude_unset)
def put_peak_cap(body: m.PeakCapUpdate, svc: Service):
    return svc.set_peak_cap(_body(body))


@router.put("/kitchen/authority", response_model=m.Ok, **_exclude_unset)
def put_authority(body: m.ClaudeAuthority, svc: Service):
    return svc.set_authority(_body(body))


@router.put("/kitchen/preferences", response_model=m.Ok, **_exclude_unset)
def put_preferences(body: m.PreferencesUpdate, svc: Service):
    return svc.set_preferences(_body(body))


# ---------------------------------------------------------------- clock, devices, events

@router.post("/sim/control", response_model=m.ClockState, **_exclude_unset)
async def post_sim_control(body: m.SimControlRequest, rt: Runtime):
    request = _body(body)
    return await rt.control(request["action"], request.get("speed"))


@router.post("/devices/{device_id}/command", response_model=m.Command, responses=R404, **_exclude_unset)
async def post_device_command(device_id: str, body: m.DeviceCommandRequest, rt: Runtime):
    return rt.owner_command(device_id, _body(body))


@router.post("/events/customers", response_model=m.Ok, **_exclude_unset)
async def post_events_customers(body: m.CustomerEventRequest, rt: Runtime):
    return rt.customer_event(_body(body))


# ---------------------------------------------------------------- decisions, escalations, proposals

@router.get("/decisions", response_model=list[m.Decision], **_exclude_unset)
def get_decisions(svc: Service, limit: Annotated[int, Query(ge=1)] = 50):
    return svc.decisions(limit)


@router.post("/decisions/{decision_id}/undo", response_model=m.Decision, responses=R404, **_exclude_unset)
def post_decision_undo(decision_id: str, svc: Service):
    return svc.undo_decision(decision_id)


@router.get("/escalations", response_model=list[m.Escalation], **_exclude_unset)
def get_escalations(svc: Service, status: m.EscalationStatus | None = None):
    return svc.escalations(status)


# async: the owner's choice is published by runtime/escalations.py, which lives on the event loop.
@router.post("/escalations/{escalation_id}/resolve", response_model=m.Escalation, responses=R404, **_exclude_unset)
async def post_escalation_resolve(escalation_id: str, body: m.EscalationResolveRequest, rt: Runtime):
    return await rt.escalations.resolve_by_owner(escalation_id, _body(body)["option_id"])


@router.get("/proposals", response_model=list[m.Proposal], **_exclude_unset)
def get_proposals(book: Proposals, status: m.ProposalStatus | None = None):
    return book.list(status)


# The Concierge proposes the paid plan's authority (code-written payload, never the model); the owner still confirms.
@router.post("/proposals", response_model=m.Proposal, dependencies=AgentOnly, responses={401: _ERR}, **_exclude_unset)
def post_proposal(body: m.ProposalCreateRequest, book: Proposals):
    req = _body(body)
    return book.create(req["kind"], req["payload"], req["summary"])


# async: applying a customer_event proposal schedules a surge in the run loop, which lives on the event loop.
# The Concierge confirms with X-Agent-Token (an ASI:One reply or card) → `confirmed_via: asi_one`; the dashboard sends none.
@router.post("/proposals/{proposal_id}/confirm", response_model=m.Proposal, responses={**R404, 401: _ERR},
             **_exclude_unset)
async def post_proposal_confirm(proposal_id: str, body: m.ProposalConfirmRequest, book: Proposals, request: Request,
                                x_agent_token: Annotated[str | None, Header()] = None):
    via = "ui"
    if x_agent_token is not None:
        _require_agent_token(request, x_agent_token)
        via = "asi_one"
    return book.confirm(proposal_id, _body(body)["confirm"], via=via)


# ---------------------------------------------------------------- backtest, chat

@router.post("/backtest/run", response_model=m.BacktestRunStarted, **_exclude_unset)
def post_backtest_run(body: m.BacktestRunRequest, svc: Service):
    return svc.run_backtest(_body(body))


@router.get("/backtest/{run_id}", response_model=list[m.BacktestResult], responses=R404, **_exclude_unset)
def get_backtest(run_id: str, svc: Service):
    return svc.backtest(run_id)


@router.post("/chat", response_model=m.ChatStarted, **_exclude_unset)
async def post_chat(body: m.ChatRequest, agent: Agent):
    return agent.start_chat(_body(body)["message"])


# ---------------------------------------------------------------- context + agents (agents send X-Agent-Token)

@router.get("/context", response_model=m.Context, **_exclude_unset)
def get_context(svc: Service):
    return svc.get_context()


@router.post("/context", response_model=m.Ok, dependencies=AgentOnly, responses={401: _ERR}, **_exclude_unset)
async def post_context(body: m.Context, rt: Runtime):
    return rt.post_context(_body(body))


@router.post(
    "/context/crowd-effect", response_model=m.Ok, dependencies=AgentOnly, responses={401: _ERR}, **_exclude_unset
)
async def post_context_crowd_effect(body: m.CrowdEffectRequest, rt: Runtime):
    return rt.set_crowd_effect(_body(body))


@router.post("/agent-log", response_model=m.Ok, dependencies=AgentOnly, responses={401: _ERR}, **_exclude_unset)
async def post_agent_log(body: m.AgentLog, rt: Runtime):
    return rt.log_agent(_body(body))


# ---------------------------------------------------------------- health

@router.get("/health", response_model=m.Health)
def get_health(request: Request):
    s: Settings = request.app.state.settings
    return m.Health(
        ok=True,
        kitchen_impl=s.kitchen_impl,
        live_transport=s.live_transport,
        store=s.store,
        hardware=s.hardware,
        # Kept current by runtime/hub_link.py (on_host)
        sim_host="connected" if request.app.state.sim_host_connected else "offline",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.broadcaster.bind_loop(asyncio.get_running_loop())
        yield
        await app.state.agent.wait_chats()
        await app.state.broadcaster.stop()
        await app.state.runtime.stop()
        close = getattr(app.state.store, "close", None)  # Convex: send what is still queued
        if close is not None:
            await asyncio.to_thread(close)

    app = FastAPI(
        title="WattWise API", version="0.1.0", description="CONTRACTS.md §2 (REST + viewer /ws)", lifespan=lifespan
    )
    app.state.settings = settings
    engine = load_engine(settings.kitchen_impl)
    fake = settings.kitchen_impl == "fake"
    app.state.broadcaster = broadcaster = Broadcaster()
    # Fake mode starts from the recorded Demo Café records; the real engine starts from an empty store.
    # Warnings (store_down, hub_offline) are /ws messages whatever the live transport.
    store = create_store(settings.store, seed_dir=settings.fixtures_dir / "convex" / "tables" if fake else None,
                         convex_url=settings.convex_url, on_warning=broadcaster.send_soon)
    if fake:
        seed_fake_scenario(store, settings.fixtures_dir)
    app.state.store = store
    app.state.service = service = KitchenService(settings.fixtures_dir, engine, store)
    app.state.sim_host_connected = False

    def _sim_host_changed(connected: bool) -> None:
        app.state.sim_host_connected = connected
        app.state.runtime.on_host(connected)

    # Warnings are /ws messages whatever the live transport (SpacetimeDB has no warning table).
    app.state.hub = hub = HubLink(
        on_status=lambda reason: app.state.runtime.on_hub_status(reason),
        on_warning=broadcaster.broadcast,
        on_host=_sim_host_changed,
    )
    port, _ = create_live(settings.live_transport, broadcaster.broadcast)
    fallback = None if isinstance(port, WsLive) else WsLive(broadcaster.broadcast)
    live = LivePublisher(port, fallback=fallback, on_warning=broadcaster.broadcast)
    bridge = DeviceBridge(settings.hardware, store, on_warning=broadcaster.send_soon)
    app.state.runtime = runtime = RunLoop(service=service, hub=hub, live=live, store=store,
                                          start_sim_ts=settings.sim_start_ts, publish_ws=broadcaster.send_soon,
                                          demo_mode=settings.demo_mode, bridge=bridge)
    service.on_escalation = runtime.escalations.changed
    # Proposals and chat use /ws whatever the live transport (CONTRACTS.md §2).
    app.state.proposals = proposals = ProposalBook(
        service, clock=lambda: runtime.sim_ts, publish=broadcaster.send_soon,
        schedule_customer_event=runtime.schedule_customer_event,
    )
    app.state.agent_tools = tools = AgentTools(service, proposals, runtime.set_crowd_effect)
    app.state.agent = ClaudeAgent(
        tools, create_llm(settings.claude_provider, settings.anthropic_api_key, settings.anthropic_model),
        publish=broadcaster.send_soon, timezone=service.tariff["timezone"], engine_rule_error=engine.RuleError,
    )
    runtime.escalations.agent = app.state.agent  # Claude off (no key) → escalations wait for the owner or the default
    install_error_handlers(app, engine.RuleError)
    app.include_router(router)

    @app.websocket("/ws")
    async def viewer_socket(websocket: WebSocket) -> None:
        await websocket.app.state.broadcaster.serve(websocket)

    @app.websocket("/ws/hub")
    async def hub_socket(websocket: WebSocket) -> None:
        await websocket.app.state.hub.serve(websocket)

    return app


app = create_app()
