"""The Claude agent the dashboard chat and the Concierge share (API.md "AI agent", AGENTS.md "Claude").

Anthropic SDK with tool use over `agent/tools.py`: the model reads engine numbers through tools and changes state only
through the two bounded tools; every other change is a `propose_*` Proposal. `CLAUDE_PROVIDER=anthropic` (default) |
`foundry` (STUB); model from `ANTHROPIC_MODEL`. With no `ANTHROPIC_API_KEY` (or a failed / slow call) everything falls
back to `agent/templates.py`: the kitchen runs identically with Claude off.

- `start_chat(message)` → `{chat_id}`; the reply streams on `/ws` as `chat_delta` messages, then one `chat_done`.
- `explain_decision(decision, device_name)` → (text, "ai" | "template"), 3 s timeout.
- `decide_escalation(escalation, council=[...])` → the engine's resolved Escalation, or None (8 s timeout, no choice):
  the engine's default then applies at the deadline. `council` names the Context parts the context agents posted for this
  escalation's window; the rationale cites them by source with numbers copied from the context. Used by
  `runtime/escalations.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from api.errors import NoKitchenError, NotFoundError, NotRecordedError, RuleError

from . import templates
from .tools import CHAT_TOOLS, ESCALATION_TOOLS, AgentTools, ToolInputError

log = logging.getLogger("agent.claude")

DEFAULT_MODEL = "claude-opus-5-5"
PROVIDERS = ("anthropic", "foundry")
MAX_TOKENS = 16000
MAX_TURNS = 8  # model turns per answer (each tool round trip is one)
EXPLAIN_TIMEOUT_S = 3.0
ESCALATION_TIMEOUT_S = 8.0
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # on a refusal the API re-runs the request on a fallback model
EXPLAIN_TOOLS = ("explain_decision", "get_forecast", "get_context")
# Run on the event loop, not a worker thread: they publish through the run loop's live port.
LOOP_TOOLS = ("set_crowd_effect",)
# Tool errors the model may read (a short reason); anything else is logged and reported as a plain failure.
TOOL_ERRORS = (ToolInputError, NotFoundError, NoKitchenError, NotRecordedError, RuleError)

SYSTEM_PROMPT = """You are WattWise's assistant for a restaurant owner. Be brief, plain and friendly.
- Only state numbers that appear in tool results, exactly as returned; field names carry the units (_kw, _kwh, _usd,
  _min, _pct, _c). If you need a number, call a tool. If no tool gives it, say you don't have that number. Never
  estimate, add, subtract, average or convert numbers yourself.
- You cannot control devices. To change a device's importance, the peak cap, undo a decision, pick an escalation
  option the owner asked for, or add a customer event, call the matching propose_* tool. It applies only after the
  owner confirms; tell them it is waiting for their confirmation.
- When explaining a decision, say what changed, why (its reason_code) and its effect, from the tool.
- Escalation options are numbered 1, 2, 3... in the order get_escalation lists them; "option 2" is the second entry.
  When you list options, number them that way.
- A message may start with the earlier chat for reference. Use it only to understand what the owner refers to (e.g.
  "undo that"); take every number from a tool call made now. Confirmation is handled outside you: never claim a change
  was applied.
- Times in tools are UTC. The restaurant's local time zone is {timezone}; speak in local time."""

ESCALATION_PROMPT = """
An escalation is open: the engine found no move inside the owner's rules that holds the peak target. Choose exactly
one of its offered options by calling choose_escalation_option once, with its option_id and a short rationale (one or
two sentences). Choose what best fits the context and the owner's preferences. Prefer options with within_authority
true; choose ask_owner when the trade-off is the owner's to make.
`council` lists the agents just asked about this block. In the rationale, quote the chosen option's numbers, then cite
one piece of evidence from each council agent by name, shaped like "Weather agent: <temp_c> °C at <time>", "Grid agent:
stress <stress>, <usd_per_kwh> $/kWh at <time>", "Events agent: <name>, <expected_attendance> expected at <time>". Copy those numbers exactly from
`context` (weather.hourly, prices.hourly / stress, events.items); never compute, round or convert them. If `council` is
empty, cite no agent."""
COUNCIL_AGENTS = {"weather": "Weather agent", "prices": "Grid agent", "events": "Events agent"}


# ---------------------------------------------------------------- the model behind one interface


@dataclass
class Turn:
    content: list[Any]  # the assistant's content blocks, passed back unchanged on the next request
    tool_uses: list[tuple[str, str, dict]] = field(default_factory=list)  # (tool_use_id, name, input)
    stop_reason: str | None = None

    @property
    def text(self) -> str:
        return "".join(_field(b, "text") or "" for b in self.content if _field(b, "type") == "text")


def _field(block: Any, name: str) -> Any:
    return block.get(name) if isinstance(block, dict) else getattr(block, name, None)


OnText = Callable[[str], Awaitable[None]]


class LLM(Protocol):
    async def turn(self, *, system: str, messages: list[dict], tools: list[dict], effort: str,
                   on_text: OnText | None = None) -> Turn: ...


class AnthropicLLM:
    """One streamed Messages API call per turn (anthropic >= 2.3)."""

    def __init__(self, client: Any, model: str):
        self._client = client  # anthropic.AsyncAnthropic
        self.model = model

    async def turn(self, *, system: str, messages: list[dict], tools: list[dict], effort: str,
                   on_text: OnText | None = None) -> Turn:
        async with self._client.beta.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            async for event in stream:
                if event.type == "text" and on_text is not None:
                    await on_text(event.text)
            message = await stream.get_final_message()
        uses = [(b.id, b.name, b.input) for b in message.content if b.type == "tool_use"]
        return Turn(list(message.content), uses, message.stop_reason)


def create_llm(provider: str, api_key: str | None, model: str | None) -> LLM | None:
    """None = Claude off (templates). Logged once, never raised: the kitchen runs without Claude."""
    if provider not in PROVIDERS:
        raise ValueError(f"CLAUDE_PROVIDER={provider!r}; expected one of {PROVIDERS}")
    if provider == "foundry":
        log.warning("STUB: CLAUDE_PROVIDER=foundry is not built yet; Claude is off (template text)")
        return None
    if not api_key:
        log.info("no ANTHROPIC_API_KEY; Claude is off (template text)")
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("the anthropic package is not installed; Claude is off (template text)")
        return None
    return AnthropicLLM(anthropic.AsyncAnthropic(api_key=api_key), model or DEFAULT_MODEL)


# ---------------------------------------------------------------- the agent


class ClaudeAgent:
    def __init__(self, tools: AgentTools, llm: LLM | None, *, publish: Callable[[dict], None], timezone: str = "UTC",
                 engine_rule_error: type[Exception] = RuleError):
        self._tools = tools
        self._tool_errors = (*TOOL_ERRORS, engine_rule_error)
        self._llm = llm
        self._publish = publish  # one /ws message
        self._system = SYSTEM_PROMPT.format(timezone=timezone)
        self._chat_count = 0
        self._chats: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return self._llm is not None

    # ------------------------------------------------------------ chat

    def start_chat(self, message: str) -> dict:
        """`POST /api/chat`: the reply streams over `/ws`. Call from the event loop."""
        self._chat_count += 1
        chat_id = f"chat_{self._chat_count:04d}"
        task = asyncio.get_running_loop().create_task(self._stream_chat(chat_id, message), name=chat_id)
        self._chats.add(task)
        task.add_done_callback(self._chats.discard)
        return {"chat_id": chat_id}

    async def _stream_chat(self, chat_id: str, message: str) -> None:
        async def delta(text: str) -> None:
            self._publish({"type": "chat_delta", "chat_id": chat_id, "text": text})

        try:
            await self.reply(message, delta)
        finally:
            self._publish({"type": "chat_done", "chat_id": chat_id})

    async def reply(self, message: str, on_text: OnText) -> tuple[str, str]:
        """One answer, streamed through `on_text` → (full text, "ai" | "template"). Never raises."""
        streamed = False

        async def forward(text: str) -> None:
            nonlocal streamed
            streamed = True
            await on_text(text)

        if self._llm is not None:
            try:
                text = await self._run(self._system, [{"role": "user", "content": message}], CHAT_TOOLS,
                                       effort="low", on_text=forward)
                return text, "ai"
            except Exception:
                log.exception("chat failed; answering with template text")
                if streamed:
                    await on_text(" " + templates.CHAT_FAILED)
                    return templates.CHAT_FAILED, "template"
        text = templates.chat_reply(await self._meter())
        await on_text(text)
        return text, "template"

    async def _meter(self) -> dict | None:
        try:
            return (await asyncio.to_thread(self._tools.get_kitchen_state))["meter"]
        except Exception:
            return None

    async def wait_chats(self) -> None:
        """Wait for every streaming reply (tests, shutdown)."""
        if self._chats:
            await asyncio.gather(*list(self._chats), return_exceptions=True)

    # ------------------------------------------------------------ explanations

    async def explain_decision(self, decision: dict, device_name: str) -> tuple[str, str]:
        template = templates.explain_decision(decision, device_name)
        if self._llm is None:
            return template, "template"
        prompt = (f"Explain this decision about {device_name} to the owner in one sentence:\n"
                  f"{json.dumps(decision)}")
        try:
            text = await asyncio.wait_for(
                self._run(self._system, [{"role": "user", "content": prompt}], EXPLAIN_TOOLS, effort="low"),
                EXPLAIN_TIMEOUT_S)
        except Exception:  # timeout or API error: the template stays
            log.info("explanation for %s fell back to the template", decision.get("decision_id"))
            return template, "template"
        return (text.strip(), "ai") if text.strip() else (template, "template")

    # ------------------------------------------------------------ escalations

    async def decide_escalation(self, escalation: dict, council: list[str] | None = None) -> dict | None:
        """Claude picks one offered option (enum-constrained); the engine validates it. None = no choice."""
        if self._llm is None:
            return None
        chosen: dict = {}
        try:
            snapshot = await asyncio.to_thread(self._tools.get_kitchen_state)
            config = snapshot["config"]
            facts = {"escalation": escalation, "context": snapshot["context"],
                     "owner_preferences": config.get("owner_preferences"), "authority": config.get("authority"),
                     "council": [COUNCIL_AGENTS[p] for p in council or () if p in COUNCIL_AGENTS]}
            await asyncio.wait_for(
                self._run(self._system + ESCALATION_PROMPT, [{"role": "user", "content": json.dumps(facts)}],
                          ESCALATION_TOOLS, effort="medium", escalation=escalation, chosen=chosen),
                ESCALATION_TIMEOUT_S)
        except Exception:
            log.warning("Claude made no choice for %s; the engine's default applies at the deadline",
                        escalation["escalation_id"], exc_info=True)
        return chosen.get("escalation")

    # ------------------------------------------------------------ the tool loop

    async def _run(self, system: str, messages: list[dict], allowed: tuple[str, ...], *, effort: str,
                   on_text: OnText | None = None, escalation: dict | None = None, chosen: dict | None = None) -> str:
        tools = AgentTools.schemas(allowed, escalation)
        text = []
        for _ in range(MAX_TURNS):
            turn = await self._llm.turn(system=system, messages=messages, tools=tools, effort=effort, on_text=on_text)
            text.append(turn.text)
            messages.append({"role": "assistant", "content": turn.content})
            if turn.stop_reason == "pause_turn":
                continue
            if not turn.tool_uses or turn.stop_reason in ("refusal", "max_tokens"):
                break  # an answer, a refusal, or a truncated (unsafe to run) tool input
            results = await asyncio.gather(*(self._tool_result(use, allowed, escalation, chosen)
                                             for use in turn.tool_uses))
            messages.append({"role": "user", "content": list(results)})
        else:
            log.warning("tool loop stopped after %s turns", MAX_TURNS)
        return "".join(text)

    async def _tool_result(self, use: tuple[str, str, dict], allowed: tuple[str, ...], escalation: dict | None,
                           chosen: dict | None) -> dict:
        tool_use_id, name, tool_input = use
        try:
            if name in LOOP_TOOLS:
                output = self._tools.call(name, tool_input, allowed=allowed, escalation=escalation)
            else:
                output = await asyncio.to_thread(self._tools.call, name, tool_input, allowed=allowed,
                                                 escalation=escalation)
        except self._tool_errors as exc:
            return {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": str(exc)}
        except Exception:
            log.exception("tool %s failed", name)
            return {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True,
                    "content": "The tool failed; tell the owner you couldn't get that right now."}
        if name == "choose_escalation_option" and chosen is not None:
            chosen["escalation"] = output
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(output)}
