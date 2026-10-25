"""ASI:One Interactive Cards for the Concierge (Innovation Lab "ASI:One Interactive Cards", card protocol version 1).

A card rides in a normal Agent Chat Protocol reply: the TextContent narration plus one MetadataContent whose metadata is
`dict[str, str]`: `card_protocol_version` "1", `requires_card_interaction` "true", `card_kind`, `card_payload` (JSON).
When ASI:One rejects a card it shows the TextContent alone, so every card carries a `fallback` text that says the same
thing and how to answer by typing.

Four cards: escalation (custom), proposal (review), forecast (custom, informational), upgrade (review).
Every number is copied from an API / tool result and rendered as received (`str(value)`); this module computes none.

A button press comes back as a chat message: the selection JSON (direct @mention) or the planner's prose naming every
identifier in it. `parse_selection` reads both; the Concierge's code (never a model) acts on the result.

No uagents import: the backend tests load it with `owner_chat.py`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "1"
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_DEPTH = 8  # custom element trees, the root counts as level 1
DRAWER_WIDTH_PX = "540"
BAR_WIDTH = 20  # characters of the longest forecast bar

CONFIRM_HINT = 'Reply "confirm" to apply it or "cancel" to drop it.'
EXPIRED = "Sorry, that option expired."

# Selection actions (prefixed so the planner's prose and any typed text can't collide with them).
CHOOSE_OPTION = "wattwise_escalation_option"
PROPOSAL_CONFIRM = "wattwise_proposal_confirm"
PROPOSAL_CANCEL = "wattwise_proposal_cancel"
UPGRADE = "wattwise_upgrade"
STAY_FREE = "wattwise_stay_free"
ACTIONS = (CHOOSE_OPTION, PROPOSAL_CONFIRM, PROPOSAL_CANCEL, UPGRADE, STAY_FREE)
_REQUIRED = {CHOOSE_OPTION: ("escalation_id", "option_id"),
             PROPOSAL_CONFIRM: ("proposal_id",), PROPOSAL_CANCEL: ("proposal_id",),
             UPGRADE: (), STAY_FREE: ()}

ASK_OWNER = "ask_owner"  # no action or owner-override button is ever rendered for this sentinel option
RULE_BREAK_LABELS = {"cap_overrun": "cap overrun", "below_min_power": "below minimum power",
                     "past_deadline": "past deadline", "over_max_reduce": "over max reduce time",
                     "over_max_delay": "over max delay"}
UNIT_LABELS = {"pct": "%"}
PROPOSAL_KIND_LABELS = {"importance": "Device importance", "peak_cap": "Peak cap", "authority": "Claude's authority",
                        "undo_decision": "Undo a decision", "resolve_escalation": "Escalation choice",
                        "customer_event": "Customer event"}


# ---------------------------------------------------------------- the wire shape

@dataclass(frozen=True)
class Card:
    kind: str  # carousel | detail | form | review | custom
    payload: dict
    fallback: str
    terminal: bool = False  # informational only: no input expected

    def metadata(self) -> dict[str, str]:
        meta = {"card_protocol_version": PROTOCOL_VERSION, "requires_card_interaction": "true",
                "card_kind": self.kind, "card_payload": json.dumps(self.payload, ensure_ascii=False)}
        if self.kind == "custom":
            meta["preferred_drawer_width_px"] = DRAWER_WIDTH_PX
        if self.terminal:
            meta["is_terminal"] = "true"
        return meta

    def fits(self) -> bool:
        """Within ASI:One's limits; a card that isn't is sent as its text only."""
        size_ok = len(self.metadata()["card_payload"].encode("utf-8")) <= MAX_PAYLOAD_BYTES
        return size_ok and (self.kind != "custom" or depth(self.payload["root"]) <= MAX_DEPTH)


@dataclass(frozen=True)
class Reply:
    """One chat reply: the text always, a card when one fits. `text` already ends with the card's fallback."""
    text: str
    card: Card | None = None

    @classmethod
    def with_card(cls, text: str, card: Card | None) -> Reply:
        if card is None or not card.fits():
            return cls(text + (f"\n\n{card.fallback}" if card is not None else ""))
        return cls(f"{text}\n\n{card.fallback}" if text else card.fallback, card)


def depth(node: Any) -> int:
    """Nesting level of a custom element tree (an element is one level; list items are not elements)."""
    if not isinstance(node, dict):
        return 0
    children = list(node.get("children") or [])
    for item in node.get("items") or []:
        children += item.get("children") or []
    return 1 + max((depth(c) for c in children), default=0)


# ---------------------------------------------------------------- selections (button presses)

@dataclass(frozen=True)
class Selection:
    action: str | None  # None: a card selection we don't know → EXPIRED
    values: dict

    def get(self, key: str) -> Any:
        return self.values.get(key)


_ACTION_RE = re.compile(r"\bwattwise_[a-z_]+\b")
_ESCALATION_RE = re.compile(r"\be_\d+\b")
_PROPOSAL_RE = re.compile(r"\bp_\d+\b")
# CONTRACTS.md §1 Escalation: option ids are accept_overrun, deep_reduce_<type_id>, extend_delay_<type_id>, ask_owner.
_OPTION_RE = re.compile(r"\b(accept_overrun|ask_owner|deep_reduce_[a-z0-9_]+|extend_delay_[a-z0-9_]+)\b")


def parse_selection(text: str) -> Selection | None:
    """A card button press, or None for an ordinary message. JSON first (direct @mention), then the planner's prose."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        return _checked(data.get("action"), data)
    if data is not None:  # a bare number or string: ordinary text
        return None
    actions = _ACTION_RE.findall(text)
    if not actions:
        return None
    values: dict[str, str] = {}
    for key, pattern in (("escalation_id", _ESCALATION_RE), ("proposal_id", _PROPOSAL_RE), ("option_id", _OPTION_RE)):
        if found := pattern.search(text):
            values[key] = found.group(0)
    return _checked(actions[0], values)


def _checked(action: Any, values: dict) -> Selection:
    if action not in ACTIONS or any(not isinstance(values.get(k), str) for k in _REQUIRED[action]):
        return Selection(None, values)
    return Selection(action, values)


# ---------------------------------------------------------------- number rendering (as received, never computed)

def num(value: Any) -> str:
    return str(value)


def _qty(value: Any, unit: str) -> str:
    unit = UNIT_LABELS.get(unit, unit)
    return f"{num(value)} {unit}" if unit != "%" else f"{num(value)} %"


def _sentence(text: str) -> str:
    return text.strip().rstrip(".") + "."


def _text(value: str, style: str | None = None) -> dict:
    return {"type": "text", "value": value, **({"style": style} if style else {})}


def _button(label: str, selection: dict, primary: bool = False) -> dict:
    return {"type": "button", "label": label, "primary": primary, "action": {"selection": selection}}


# ---------------------------------------------------------------- 1. escalation (custom)

def rule_break_text(rb: dict) -> str:
    label = RULE_BREAK_LABELS.get(rb["kind"], rb["kind"])
    who = f"{rb['device_id']} " if rb.get("device_id") else ""
    return f"{who}{label} {_qty(rb['amount'], rb['unit'])}"


def problem_text(problem: dict) -> str:
    return (f"Forecast {num(problem['forecast_peak_kw'])} kW against a {num(problem['target_kw'])} kW target "
            f"({num(problem['excess_kw'])} kW over): {problem['reason']}.")


def option_lines(option: dict) -> list[str]:
    """The engine's numbers for one option, each line as the card shows it."""
    projected = option.get("projected")
    lines = []
    if projected is not None:
        lines += [f"Peak after: {num(projected['peak_kw'])} kW", f"Extra cost: ${num(projected['cost_delta_usd'])}",
                  f"Indoor temp change: {num(projected['max_indoor_temp_change_c'])} °C"]
    breaks = option.get("rule_breaks") or []
    lines.append("Breaks: " + "; ".join(rule_break_text(rb) for rb in breaks) if breaks else "Breaks no rule")
    return lines


def numbered_options(escalation: dict) -> list[tuple[int, dict]]:
    """(N, option) in engine order; ``ask_owner`` has no action and is never an owner override."""
    return [(n, o) for n, o in enumerate(escalation["options"], 1) if o["option_id"] != ASK_OWNER]


def claude_choice(escalation: dict) -> dict | None:
    """The option Claude resolved, if this report has one."""
    if escalation.get("resolved_by") != "claude" or not escalation.get("chosen_option_id"):
        return None
    return next((o for o in escalation["options"] if o["option_id"] == escalation["chosen_option_id"]), None)


def _rank_harm_lines(option: dict) -> list[str]:
    """Show engine-provided ranking fields without calculating or normalizing them."""
    lines = []
    if "rank" in option:
        lines.append(f"Rank: {num(option['rank'])}")
    if "harm_score" in option:
        lines.append(f"Harm score: {num(option['harm_score'])}")
    return lines


def escalation_card(escalation: dict, *, allow_owner_override: bool = True) -> Card:
    """An escalation *report*, not an approval request.

    The engine fallback is already active. The only optional interaction is a direct owner override, which always goes
    straight to the resolve endpoint; the card never requires a decision or confirmation from the owner.
    """
    eid = escalation["escalation_id"]
    pick = claude_choice(escalation)
    options = numbered_options(escalation)
    number = {o["option_id"]: n for n, o in options}
    default = next((o for o in escalation["options"] if o["option_id"] == escalation["default_option_id"]), None)
    active = next((o for o in escalation["options"] if o["option_id"] == escalation.get("active_option_id")), None)

    children: list[dict] = [_text(problem_text(escalation["problem"]), "emphasis")]
    if active is not None:
        children.append({"type": "section", "title": f"Active option: option {number.get(active['option_id'], active['option_id'])}",
                         "subtitle": active["summary"],
                         "children": [_text(line, "muted") for line in _rank_harm_lines(active)]})
    elif default is not None:
        children.append(_text(f"Engine fallback: {default['summary']}", "muted"))
    if pick is not None:
        rationale = escalation.get("rationale")
        report = f"Claude chose {pick['summary']}" + (f" because {rationale}" if rationale else ".")
        children.append({"type": "section", "title": "Claude's resolution", "subtitle": report,
                         "children": [_text(line, "muted") for line in _rank_harm_lines(pick)]})
    children.append({"type": "divider"})
    for n, option in options:
        badges = []
        if active is not None and option["option_id"] == active["option_id"]:
            badges.append({"type": "badge", "label": "Active", "variant": "success"})
        if pick is not None and option["option_id"] == pick["option_id"]:
            badges.append({"type": "badge", "label": "Claude chose", "variant": "info"})
        badges.append({"type": "badge", "label": "Within Claude's authority", "variant": "info"} if option[
            "within_authority"] else {"type": "badge", "label": "Outside Claude's authority", "variant": "warning"})
        if option["option_id"] == escalation["default_option_id"]:
            badges.append({"type": "badge", "label": "Engine fallback", "variant": "info"})
        option_children = [
            {"type": "group", "direction": "row", "gap": 8, "children": badges},
            *(_text(line) for line in [*option_lines(option), *_rank_harm_lines(option)]),
        ]
        if allow_owner_override and (active is None or option["option_id"] != active["option_id"]):
            option_children.append(_button(f"Override: option {n}",
                                           {"action": CHOOSE_OPTION, "escalation_id": eid,
                                            "option_id": option["option_id"]}))
        children.append({"type": "section", "title": f"Option {n}", "subtitle": option["summary"],
                         "children": option_children})

    payload = {"root": {"type": "section", "title": "Escalation report", "subtitle": escalation["problem"]["reason"],
                        "children": children}}

    lines = [f"Escalation report. {problem_text(escalation['problem'])}"]
    if active is not None:
        lines.append(f"Active option: {active['summary']}." +
                     (f" Rank {num(active['rank'])}." if "rank" in active else "") +
                     (f" Harm score {num(active['harm_score'])}." if "harm_score" in active else ""))
    elif default is not None:
        lines.append(f"Engine fallback: {default['summary']}.")
    if pick is not None:
        rationale = escalation.get("rationale")
        lines.append(f"Claude chose {pick['summary']}" + (f" because {rationale}" if rationale else "."))
    for n, option in options:
        authority = "within Claude's authority" if option["within_authority"] else "outside Claude's authority"
        ranking = _rank_harm_lines(option)
        lines.append(f"{n}. {option['summary']}: " + ", ".join([*option_lines(option), *ranking]) +
                     f" ({authority}).")
    if allow_owner_override and options:
        lines.append('Owner override only: reply "choose option N" to switch the active option.')
    return Card("custom", payload, "\n".join(lines))


# ---------------------------------------------------------------- 2. proposal (review)

def proposal_text(proposal: dict) -> str:
    return f"Waiting for your confirmation: {_sentence(proposal['summary'])} {CONFIRM_HINT}"


def proposal_card(proposal: dict) -> Card:
    pid = proposal["proposal_id"]
    payload = {
        "title": "Waiting for your confirmation",
        "summary_rows": [{"label": "Change", "value": proposal["summary"]},
                         {"label": "Kind", "value": PROPOSAL_KIND_LABELS.get(proposal["kind"], proposal["kind"])}],
        "approve_cta": {"label": "Confirm", "primary": True, "selection": {"action": PROPOSAL_CONFIRM, "proposal_id": pid}},
        "reject_cta": {"label": "Cancel", "selection": {"action": PROPOSAL_CANCEL, "proposal_id": pid}},
    }
    return Card("review", payload, proposal_text(proposal))


# ---------------------------------------------------------------- 3. forecast (custom, informational)

def forecast_card(forecast_kw: list[float], meter: dict, moves: list[dict], *, device_names: dict[str, str],
                  as_of: str | None = None) -> Card:
    """The engine's next-2-h forecast (15-min steps), the cap line and the moves the engine just planned.
    The cap is `peak_cap_kw` in cap mode, else the engine's `target_kw` (minimize mode)."""
    cap_kw = meter["peak_cap_kw"] if meter.get("peak_cap_kw") is not None else meter["target_kw"]
    cap_label = "Cap" if meter.get("peak_cap_kw") is not None else "Target"
    scale = max([*forecast_kw, cap_kw]) or 1  # bar lengths only: drawn, never shown as a number

    rows, lines = [], []
    for i, kw in enumerate(forecast_kw):
        step = f"+{15 * (i + 1)} min"  # CONTRACTS.md: the forecast is one value per 15 min
        bar = "█" * max(1, round(BAR_WIDTH * kw / scale))
        over = kw > cap_kw
        rows.append({"type": "group", "direction": "row", "gap": 8, "children": [
            _text(step, "muted"), _text(f"{num(kw)} kW", "emphasis" if over else None), _text(bar),
            *([{"type": "badge", "label": f"over {cap_label.lower()}", "variant": "warning"}] if over else []),
        ]})
        lines.append(f"{step}: {num(kw)} kW" + (f" (over {cap_label.lower()})" if over else ""))

    move_lines = [move_text(m, device_names) for m in moves] or ["No new moves planned."]
    children = [_text(f"{cap_label}: {num(cap_kw)} kW", "emphasis"), *rows, {"type": "divider"},
                {"type": "section", "title": "Next planned moves", "children": [_text(t) for t in move_lines]}]
    title = "Next 2 hours"
    payload = {"root": {"type": "section", "title": title,
                        **({"subtitle": f"Engine forecast at {as_of}"} if as_of else {}), "children": children}}
    fallback = "\n".join([f"{title} ({cap_label.lower()} {num(cap_kw)} kW):", *lines, "Next planned moves:",
                          *move_lines])
    return Card("custom", payload, fallback, terminal=True)


def move_text(decision: dict, device_names: dict[str, str]) -> str:
    """One Decision as a line: device, action (CONTRACTS.md §1 Command: delay = minutes, reduce = power %), effect."""
    name = device_names.get(decision["device_id"], decision["device_id"])
    action, value = decision["action"], decision.get("value")
    what = {"delay": f"delay {num(value)} min", "reduce": f"reduce to {num(value)} %"}.get(
        action, action if value is None else f"{action} {num(value)}")
    effect = decision.get("effect") or {}
    if "peak_before_kw" in effect and "peak_after_kw" in effect:
        what += f" (peak {num(effect['peak_before_kw'])} → {num(effect['peak_after_kw'])} kW)"
    return f"{name}: {what}"


# ---------------------------------------------------------------- 4. upgrade (review)

def upgrade_card(*, paid_summary: str, amount: str, currency: str) -> Card:
    """Free vs paid. `paid_summary`: the authority the paid plan proposes (upgrade.authority_summary)."""
    price = f"{amount} {currency} (Stripe test mode)"
    free = "The engine fallback remains active for every escalation."
    after = "Claude can choose only engine-approved options within its authority."
    payload = {
        "title": "Let Claude handle tonight's decisions",
        "summary_rows": [{"label": "Free plan", "value": free}, {"label": "Paid plan", "value": _sentence(paid_summary)},
                         {"label": "Price", "value": price}, {"label": "After paying", "value": after}],
        "approve_cta": {"label": "Upgrade", "primary": True, "selection": {"action": UPGRADE}},
        "reject_cta": {"label": "Stay free", "selection": {"action": STAY_FREE}},
    }
    fallback = (f"Free plan: {free} Paid plan, {price}: {_sentence(paid_summary)} {after} "
                'Reply "upgrade" to pay, or "stay free".')
    return Card("review", payload, fallback)
