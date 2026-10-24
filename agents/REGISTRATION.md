# Concierge registration checklist (Suyog's notes)

## Run it
- [ ] `python -m venv agents/.venv` then `agents/.venv/Scripts/pip install -r agents/requirements.txt`
- [ ] Set `FETCH_AGENT_SEED` (long random phrase, keep it secret, never commit; the same seed = the same address)
- [ ] `agents/.venv/Scripts/python agents/concierge.py` (port `CONCIERGE_PORT`, default 8001)
- [ ] Log shows the agent address and "Agent inspector available at ..."
- Expected before connecting: "Agent mailbox not found" (fixed by the next section) and "not enough funds to register on
  Almanac contract" (harmless: Almanac **API** registration is what mailbox agents need)

## Connect the mailbox
- [ ] Open the inspector link (Chrome 142+: allow Local Network Access for agentverse.ai)
- [ ] Connect -> Mailbox -> Finish
- [ ] Log shows "Mailbox access token acquired" and "Registration on Almanac API successful"; restart if asked
- [ ] Agentverse "My Agents" shows the agent as **Active**

## Agentverse profile
- [x] Profile name: **WattWise Concierge**
- [x] Description (v2): `Lowers a restaurant's electricity demand charges by forecasting and shifting appliance load. Connected to your kitchen: ask why your restaurant electricity bill is high, how to lower demand charges, or what lunch will cost you in power today.`
- [x] README: contents of `agents/README_concierge.md` (v2, structured per Agentverse README guidelines; the published copy was edited in the profile UI to add "lower demand charges")
- [x] Handle: `@wattwise` (`CONCIERGE_HANDLE` to change; max 20 chars)
- Description, README and handle are sent **only on inspector Connect**. After any edit: stop the agent, start it, open the
  inspector link, Connect -> Mailbox again (or paste the text into the Agentverse profile by hand)
- [x] Keywords (Discovery tab -> My Keywords, set 2026-10-24, each one appears in the README): restaurant electricity bill,
  restaurant energy bill, demand charge, lower demand charges, peak power, peak demand, utility bill, commercial kitchen,
  electricity cost, cafe
- [x] Avatar uploaded (custom image)
- [x] 10+ interactions via "Chat with Agent" / dashboard Testing (Agentverse says to reach 10 before judging discoverability)
- [ ] Category / tag: **Innovation Lab** (badge first line of the README) + hackathon badge
- [x] Chat Protocol listed under the agent's protocols (manifest published)
- [x] Starter prompts: the three cold queries
- [x] Status **active / mailbox** after the 10:57 local restart (index `last_updated` 17:52 UTC); avatar, handle, starter prompts kept

## Record
- [x] Agent address: `agent1qgr6vxnyeewx8rdsxpdu896v9w8cv5q4jmf4aw4244vu2r2nhqn9zt3gdsn` (since 2026-10-24 17:35 UTC; the first test agent `agent1qdfre3wana69ra20cckqqut0sykr6ewfr0khnucvawrf094u8y98w2av8ge` is retired)
- [ ] Agentverse profile URL: https://agentverse.ai/agents/details/agent1qgr6vxnyeewx8rdsxpdu896v9w8cv5q4jmf4aw4244vu2r2nhqn9zt3gdsn/profile (check)
- [ ] Sent name + address to Kritazya for README.md

## Index check (2026-10-24, public API `GET https://agentverse.ai/v1/search/agents/<address>`)
- Almanac: active, mailbox, AgentChatProtocol 0.3.0 digest published
- Profile indexed: name, description and README present; category `community`, `system_wide_tags` empty, 0 interactions,
  no starter prompts, no avatar
- Keyword search (`POST /v1/search/agents`) for the three queries and for "WattWise Concierge": not in the top 30 yet

- 17:40 UTC, new address: Almanac active (mailbox); profile v2 indexed with handle + avatar but `status: inactive`,
  `type: uagent` (the first agent showed `type: mailbox` after Connect -> Mailbox), so the mailbox is not attached yet

- 17:43 UTC: inspector showed the connection as "Uagent"; switched to Mailbox -> "Successfully connected"
- Mailbox path verified with a local probe agent (scratchpad `probe.py`): message delivered via
  `agentverse.ai/v2/agents/mailbox/submit`, Concierge acknowledged and replied, 5 prompts -> 10 interactions, uptime 100 %
- Still `status: inactive` in the index and the profile badge after all of that; expected fix: restart the agent so it
  re-sends its active status as a mailbox agent

- `agents/.env` seed: the value first saved (in `.env.example`, which git tracks) was the agent address, not the seed;
  moved out and blanked. The running agent still has the real seed only in its PowerShell window

## ASI:One cold queries (agent running, new chat each time)
| Query | Reached the Concierge? | Description version |
|---|---|---|
| my restaurant electricity bill is too high | No: ASI1 answered itself with generic tips (2026-10-24 10:18) | v1 |
| my restaurant electricity bill is too high | | v2 |
| lower my demand charges | No: personal AI asked 2 clarifying questions, then answered itself; "Suggested AIs" = PG&E, PG&E customer service, Utilita (WattWise still Inactive) | v2 |
| what will lunch cost me in power today | Discovered, not answered: personal AI asked 1 clarifying question, answered itself, then listed **WattWise Concierge first** under "Suggested AIs" ("Forecast lunch peak and shift load", ahead of Joe Kilowatt). After "Talk to" + adding @wattwise to the chat, the agent showed "Reasoning..." and no reply in ~4 min, while the mailbox probe got a reply in seconds | v2 active |
| @wattwise my restaurant electricity bill is too high (direct, not cold) | | v2 |

ASI:One routing note: "Messages without an @mention are routed to your personal AI by default" (Chat settings: All
messages / When useful / Mentions only). Agentverse agents reach a cold chat only when the personal AI delegates or lists
them under "Suggested AIs". Direct path that always works: `@wattwise <question>` or the profile's "Chat with Agent".

If routing misses: edit the description / README keywords, restart the agent and Connect again in the inspector so the
profile re-publishes, wait a few minutes for re-indexing, retry in a fresh ASI:One chat. Direct check: Agentverse profile -> "Chat with Agent".
