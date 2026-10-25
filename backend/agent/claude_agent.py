"""The Claude agent the dashboard chat and the Concierge share (API.md "AI agent", AGENTS.md "Claude").

Tool use over `agent/tools.py`: the model reads engine numbers through tools and changes state only through the two
bounded tools; every other change is a `propose_*` Proposal. The models live in `agent/llm.py`. Chat and explanations
try Claude, then ASI:One (`ASI1_API_KEY`), then `agent/templates.py`; escalations are Claude only (else the engine's
default). The kitchen runs identically with every model off. Both models' text is "ai"; the log names which answered.

- `start_chat(message)` → `{chat_id}`; the reply streams on `/ws` as `chat_delta` messages, then one `chat_done`.
- `explain_decision(decision, device_name)` → (text, "ai" | "template"), 3 s timeout per model.
- `decide_escalation(escalation, council=[...])` → the engine's resolved Escalation, or ``None`` (8 s timeout, no
  choice). The engine fallback is already active before this task starts. `council` names the Context parts the context
  agents posted for this escalation's window; the rationale cites them by source with numbers copied from context. Used
  by `runtime/escalations.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from api.errors import NoKitchenError, NotFoundError, NotRecordedError, RuleError

from . import templates
from .llm import LLM, OnText, Turn, create_asi1_llm, create_llm  # noqa: F401 (re-exported for callers and tests)
from .tools import CHAT_TOOLS, ESCALATION_TOOLS, AgentTools, ToolInputError

log = logging.getLogger("agent.claude")

MAX_TURNS = 8  # model turns per answer (each tool round trip is one)
EXPLAIN_TIMEOUT_S = 3.0  # per model
CHAT_TIMEOUT_S = 30.0  # per model
ESCALATION_TIMEOUT_S = 8.0
EXPLAIN_TOOLS = ("explain_decision", "get_forecast", "get_context")
# Run on the event loop: they publish through the run loop's live port.
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
An escalation is open: the engine found no move inside the owner's rules that holds the peak target. The engine has
already applied its fallback, shown as active_option_id, and the kitchen continues safely if you do not answer. Choose
exactly one option by calling choose_escalation_option once, with its option_id and a short rationale (one or two
sentences). The tool enum is the complete set you are allowed to choose: options carry within_authority flags, and the engine validates every choice.
Choose an authorized option. If the engine rejects a choice, you have one retry before its deadline. ask_owner is never an option. Do not ask the owner to decide.

The supplied ranked_options are engine facts. Compare each option's rank, harm_score and projected values exactly as
provided; do not calculate or alter them. Prefer the option that best fits the owner preferences and structured context,
not merely the rank. Weather is context only in this build: never claim weather drives, changes, or causes the load
forecast. Events/crowd and prices may be cited when the supplied context supports it.

`council` lists the agents just asked about this block. In the rationale, quote the chosen option's numbers, then cite
one piece of evidence from each council agent by name, shaped like "Weather agent: <temp_c> °C at <time>", "Grid agent:
stress <stress>, <usd_per_kwh> $/kWh at <time>", "Events agent: <name>, <expected_attendance> expected at <time>". Copy those numbers exactly from
`context` (weather.hourly, prices.hourly / stress, events.items); never compute, round or convert them. If `council` is
empty, cite no agent."""
COUNCIL_AGENTS = {"weather": "Weather agent", "prices": "Grid agent", "events": "Events agent"}


# ---------------------------------------------------------------- the agent


def _label(llm: LLM) -> str:
    """Which model answered, for the log ("asi1 (asi1)"); explanation_source is "ai" either way."""
    return f"{getattr(llm, 'name', type(llm).__name__)} ({getattr(llm, 'model', '?')})"


class ClaudeAgent:
    def __init__(self, tools: AgentTools, llm: LLM | None, *, publish: Callable[[dict], None], timezone: str = "UTC",
                 engine_rule_error: type[Exception] = RuleError, fallback: LLM | None = None):
        self._tools = tools
        self._tool_errors = (*TOOL_ERRORS, engine_rule_error)
        self._llm = llm  # Claude: chat, explanations and escalations
        self._fallback = fallback  # ASI:One: chat and explanations only, when Claude is off, fails or times out
        self._text_models = [m for m in (llm, fallback) if m is not None]
        self._publish = publish  # one /ws message
        self._system = SYSTEM_PROMPT.format(timezone=timezone)
        self._chat_count = 0
        self._chats: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        """Claude is on: escalations go to it (ASI:One never decides them)."""
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

        for llm in self._text_models:
            try:
                text = await asyncio.wait_for(
                    self._run(llm, self._system, [{"role": "user", "content": message}], CHAT_TOOLS,
                              effort="low", on_text=forward),
                    CHAT_TIMEOUT_S)
            except Exception:
                log.warning("chat via %s failed or timed out", _label(llm), exc_info=True)
                if streamed:  # the owner already saw part of this answer: no second model on top of it
                    await on_text(" " + templates.CHAT_FAILED)
                    return templates.CHAT_FAILED, "template"
                continue
            log.info("chat answered by %s", _label(llm))
            return text, "ai"
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
        prompt = (f"Explain this decision about {device_name} to the owner in one sentence:\n"
                  f"{json.dumps(decision)}")
        for llm in self._text_models:
            try:
                text = await asyncio.wait_for(
                    self._run(llm, self._system, [{"role": "user", "content": prompt}], EXPLAIN_TOOLS, effort="low"),
                    EXPLAIN_TIMEOUT_S)
            except Exception:  # timeout or API error: the next model, then the template
                log.info("explanation for %s via %s failed or timed out", decision.get("decision_id"), _label(llm))
                continue
            if text.strip():
                log.info("explanation for %s by %s", decision.get("decision_id"), _label(llm))
                return text.strip(), "ai"
        log.info("explanation for %s fell back to the template", decision.get("decision_id"))
        return templates.explain_decision(decision, device_name), "template"

    # ------------------------------------------------------------ escalations

    async def decide_escalation(self, escalation: dict, council: list[str] | None = None) -> dict | None:
        """Claude reviews evaluated options; the engine validates every choice. ``None`` means no choice.

        The run loop calls this once per new escalation id. This defensive gate also makes direct callers harmless when
        authority is disabled, missing, or has no eligible option.
        """
        if self._llm is None:
            return None
        chosen: dict = {}
        try:
            snapshot = await asyncio.to_thread(self._tools.get_kitchen_state)
            config = snapshot["config"]
            authority = config.get("authority")
            eligible = AgentTools.eligible_option_ids(escalation, authority)
            if escalation.get("status") != "open" or not eligible:
                return None
            ranked_options = [
                {
                    "option_id": option.get("option_id"),
                    "rank": option.get("rank"),
                    "harm_score": option.get("harm_score"),
                    "projected": option.get("projected"),
                    "within_authority": option.get("within_authority"),
                }
                for option in escalation.get("options", [])
            ]
            facts = {"escalation": escalation, "context": snapshot["context"],
                     "owner_preferences": config.get("owner_preferences"), "authority": authority,
                     "active_option_id": escalation.get("active_option_id"), "ranked_options": ranked_options,
                     "offered_option_ids": eligible,
                     "council": [COUNCIL_AGENTS[p] for p in council or () if p in COUNCIL_AGENTS]}
            await asyncio.wait_for(
                self._run(self._llm, self._system + ESCALATION_PROMPT, [{"role": "user", "content": json.dumps(facts)}],
                          ESCALATION_TOOLS, effort="medium", escalation=escalation, authority=authority,
                          chosen=chosen),
                ESCALATION_TIMEOUT_S)
        except Exception:
            log.warning("Claude made no choice for %s; the engine fallback remains active",
                        escalation["escalation_id"], exc_info=True)
        return chosen.get("escalation")

    # ------------------------------------------------------------ the tool loop

    async def _run(self, llm: LLM, system: str, messages: list[dict], allowed: tuple[str, ...], *, effort: str,
                   on_text: OnText | None = None, escalation: dict | None = None,
                   authority: dict | None = None, chosen: dict | None = None) -> str:
        tools = AgentTools.schemas(allowed, escalation, authority)
        text = []
        for _ in range(MAX_TURNS):
            turn = await llm.turn(system=system, messages=messages, tools=tools, effort=effort, on_text=on_text)
            text.append(turn.text)
            messages.append({"role": "assistant", "content": turn.content})
            if turn.stop_reason == "pause_turn":
                continue
            if not turn.tool_uses or turn.stop_reason in ("refusal", "max_tokens"):
                break  # an answer, a refusal, or a truncated (unsafe to run) tool input
            if chosen is not None:
                # A retry must follow a verdict, never race another choice in the same turn.
                results = []
                choice_seen = False
                for use in turn.tool_uses:
                    if use[1] == "choose_escalation_option" and choice_seen:
                        results.append({"type": "tool_result", "tool_use_id": use[0], "is_error": True,
                                        "content": "Choose only one option per turn; read its verdict before retrying."})
                        continue
                    choice_seen = choice_seen or use[1] == "choose_escalation_option"
                    results.append(await self._tool_result(use, allowed, escalation, authority, chosen))
            else:
                results = await asyncio.gather(*(self._tool_result(use, allowed, escalation, authority, chosen)
                                                 for use in turn.tool_uses))
            messages.append({"role": "user", "content": list(results)})
            if chosen is not None:
                result = chosen.get("escalation") or {}
                if result.get("status") in ("resolved", "expired_default", "obsolete") or chosen.get("attempts", 0) >= 2:
                    break
        else:
            log.warning("tool loop stopped after %s turns", MAX_TURNS)
        return "".join(text)

    async def _tool_result(self, use: tuple[str, str, dict], allowed: tuple[str, ...], escalation: dict | None,
                           authority: dict | None, chosen: dict | None) -> dict:
        tool_use_id, name, tool_input = use
        try:
            if name == "choose_escalation_option" and chosen is not None:
                if chosen.get("attempts", 0) >= 2:
                    raise ToolInputError("Only one retry is allowed; engine fallback remains active.")
                chosen["attempts"] = chosen.get("attempts", 0) + 1
            if name in LOOP_TOOLS:
                output = self._tools.call(name, tool_input, allowed=allowed, escalation=escalation,
                                          authority=authority)
            else:
                output = await asyncio.to_thread(self._tools.call, name, tool_input, allowed=allowed,
                                                  escalation=escalation, authority=authority)
        except self._tool_errors as exc:
            return {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": str(exc)}
        except Exception:
            log.exception("tool %s failed", name)
            return {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True,
                    "content": "The tool failed; tell the owner you couldn't get that right now."}
        if name == "choose_escalation_option" and chosen is not None:
            chosen["escalation"] = output
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(output)}
