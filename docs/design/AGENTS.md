# Design: Fetch.ai agents and Claude (owner: Suyog)

Fetch.ai is our **primary track**. Four uAgents in `agents/`, registered on Agentverse under Innovation Lab:
three context agents (the senses) and the **Concierge** (the owner's chat door, powered by our Claude agent).

## Principles
- Agents sense and talk; they never compute or decide. Numbers come from data APIs (raw) or the engine (derived).
- Data passes through unchanged: replies are reshaped into Context and posted as-is; Claude never retypes a number.
- Graceful degradation: any agent down → last known context; Claude down → engine defaults and template text.
- Visible collaboration: every agent message is logged (`POST /api/agent-log` → SpacetimeDB `live_agent_log`).
- The whole owner workflow works inside ASI:One with no custom frontend.

## Fetch track requirements (Cal Hacks 13.0 hackpack, as recorded by the team)
- [ ] Agents registered on **Agentverse**, categorized **Innovation Lab**.
- [ ] Concierge implements the **Agent Chat Protocol**; discoverable and usable in **ASI:One**.
- [ ] Meaningful tool execution or multi-agent orchestration; primary owner workflow completes **inside ASI:One**.
- [ ] Public repo with run/test instructions; README lists every agent **name and address** with badges
      `![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)` and `![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)`.
- [ ] 3 to 5 min demo video. Submit on Devpost **and** through the Cal Hacks ASI:One Submission Agent.
- Bonus we target: multi-agent collaboration (context agents), real-time data, recovery from failed tool calls, an agent that keeps running.
- Judging: functionality 25 %, Fetch tech 20 %, innovation 20 %, real-world impact 20 %, UX + presentation 15 %.

## Agents
| Agent | Role | Source | When |
|---|---|---|---|
| **Concierge** | Owner chat (ASI:One + dashboard relay); orchestrates the context agents; asks Claude to set `crowd_effect` | Claude agent + engine tools via API | Always on |
| **Weather** | Hourly outdoor temperature for the kitchen's location | Open-Meteo | Periodic (every `CONTEXT_INTERVAL_S`, default 600 real s) |
| **Grid** | Hourly electricity prices + stress level | CAISO price data | On request |
| **Events** (tier 2) | Events within 5 km in the next 12 h with expected attendance | Events API chosen at the event | On request |
Message models: CONTRACTS.md section 7. Tariff stays a fixed engine input (CONTRACTS.md Tariff), not an agent.

## Concierge loops
- **Context loop** (periodic, every `CONTEXT_INTERVAL_S` = 600 real s by default, and on kitchen build; never per tick): request Weather, Grid, Events → reshape → `POST /api/context` →
  log each message. Then one narrow Claude call with the events list → `set_crowd_effect` (category + reason).
- **Chat (ASI:One):** each message → the same Claude agent + tools as the dashboard → reply (Interactive Cards if time).
  Owner flows that must work: "What will lunch cost me?" · "Why did you delay the dishwasher?" · "Undo that" ·
  "Never touch the walk-in after 9 PM" (proposal → confirm) · "How much did we save this month?" ·
  "What did you decide about tonight?" (escalation + rationale) · "Choose option 2" (owner resolves an escalation).
- Confirmation (`confirm` / `yes` to the latest pending Proposal, or a card button) is matched by code, never by the model.
- Escalation choices are made by the runtime's Claude call (API.md), not inside the chat; the Concierge reports them.

## Claude
- Same agent for dashboard chat, ASI:One, explanations, crowd effect and escalation choices. Model from `ANTHROPIC_MODEL`;
  provider `CLAUDE_PROVIDER=anthropic|foundry` (Microsoft Foundry for the Azure story if billing works).
- Structured output through tool calls with enum inputs (option ids, crowd categories). Quotes only tool numbers.
- Timeouts: explanations 3 s, escalations 8 s, chat streams. Fallback: templates / engine defaults.

## Implementation notes
uAgents (`uagents`), Chat Protocol (`uagents_core.contrib.protocols.chat`), acknowledge every message,
`publish_manifest=True`, mailbox mode, seeds from env. Context agents run `--recorded` in `DEMO_MODE` (labeled `recorded`).
Failed tool call → short plain reply, session stays alive, never a stack trace. Payment Protocol only after Gate 3, if ever.
