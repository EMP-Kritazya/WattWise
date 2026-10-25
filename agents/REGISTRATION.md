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
- [ ] Category / tag: **Innovation Lab** (badge first line of the README) + hackathon badge; see "Innovation Lab
  category" below for why the index says `community` and the exact steps
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

## Innovation Lab category (all four agents; checked 2026-10-24)
What the index shows is not the Innovation Lab marker. `GET /v1/search/agents/<address>` has only two `category` values
across all of Agentverse: `fetch-ai` (Fetch-owned, `system_wide_tags: ["verified"]`) and `community` (everyone else).
Filtering the search by `innovation-lab` / `innovationlab` / `hackathon` returns 0 agents. So `community` with empty tags is
expected and cannot be changed by us. The hackpack defines Innovation Lab as: the README starts with the
`tag:innovationlab` and `tag:hackathon` badges, and the README contains the agent's name and address.
The published Concierge README had the badges (on two lines) but no address. Fixed in `README_concierge.md`: both badges
on line 1, `**Agent:** name · handle · address` under the title. Same layout in the three new READMEs.

Steps to re-publish (Concierge, then the same for each agent):
1. Stop the agent (Ctrl+C in its window); start it again (same seed, so the same address).
2. Open the inspector link from the log -> Connect -> **Mailbox** -> Finish (this sends description, README and handle).
   The Concierge's published README was hand-edited in the profile UI ("lower demand charges"); the file now has that
   wording, so the Connect overwrite loses nothing.
3. Agentverse -> My Agents -> the agent -> Overview: the README shows the two badges at the top and the address line.
   If it still shows the old text: Edit README in the profile, paste the file's contents, Save.
4. Recheck the index: `curl -s https://agentverse.ai/v1/search/agents/<address>` -> `readme` starts with
   `![tag:innovationlab]`, `status: active`, `type: mailbox`.

## Public context agents: Weather, Grid, Events
Each one runs on its own: mailbox mode, own seed (`<NAME>_AGENT_SEED`, else `FETCH_AGENT_SEED/<name>`), its typed
protocol plus AgentChatProtocol, both with `publish_manifest=True`, README `agents/README_<name>.md`, handle
`<NAME>_AGENT_HANDLE` (defaults below). Addresses are derived from the `agents/.env` seed (the one that gives the live
Concierge `agent1qgr6v...`), so they are final as long as that seed is not changed.

Run (each in its own window, from the repo root; `--recorded` for demo numbers):
`agents/.venv/Scripts/python agents/weather.py` · `agents/grid.py` · `agents/events.py`
(ports 8002 / 8003 / 8004; `AGENT_MAILBOX=0` = local endpoint only, not visible on Agentverse)

### WattWise Weather
- [x] Address: `agent1qgdzu482km7p9zaqftz2xt33xqsy8mghmdje0xqtxqxjsscj8x6ny7xlym6`
- [x] Running; log shows the address and the inspector link (live mode, terminal tab, 2026-10-24 local)
- [x] Inspector -> Connect -> Mailbox -> Finish; log: "Successfully registered as mailbox agent in Agentverse", "Registration on Almanac API successful"
- [x] Profile name **WattWise Weather**, handle `@wattwiseweather`, README `README_weather.md` (badges + address visible)
- [x] Category: Innovation Lab (README badges, see above); Discovery -> My Keywords: weather forecast, temperature forecast,
  hourly forecast, Open-Meteo, outdoor temperature
- [x] Protocols: `wattwise-weather` 0.1.0 + AgentChatProtocol 0.3.0
- [x] Starter prompts: "weather in Berkeley next 3 hours", "temperature in Paris for the next 12 hours"
- [x] Index shows **active** (`last_updated` 2026-10-25 00:31:20 UTC, `type: uagent`, see note below); profile URL https://agentverse.ai/agents/details/agent1qgdzu482km7p9zaqftz2xt33xqsy8mghmdje0xqtxqxjsscj8x6ny7xlym6/profile
- [x] ASI:One: `@wattwiseweather weather in Berkeley next 3 hours` answers

### WattWise Grid
- [x] Address: `agent1qvnts5cnkals04rcfesxwhhcs35d50025vyw4j5539d0fg0t2jwpqzunfkt`
- [x] Running; log shows the address and the inspector link (live mode, terminal tab, 2026-10-24 local)
- [x] Inspector -> Connect -> Mailbox -> Finish; log: "Successfully registered as mailbox agent in Agentverse", "Registration on Almanac API successful"
- [x] Profile name **WattWise Grid**, handle `@wattwisegrid`, README `README_grid.md` (badges + address visible)
- [x] Category: Innovation Lab (README badges, see above); Discovery -> My Keywords: electricity price, wholesale electricity
  price, CAISO, California grid, grid stress
- [x] Protocols: `wattwise-grid` 0.1.0 + AgentChatProtocol 0.3.0
- [x] Starter prompts: "price next 3 hours", "SP15 wholesale price next 6 hours"
- [x] Index shows **active** (`last_updated` 2026-10-25 00:31:47 UTC, `type: uagent`, see note below); profile URL https://agentverse.ai/agents/details/agent1qvnts5cnkals04rcfesxwhhcs35d50025vyw4j5539d0fg0t2jwpqzunfkt/profile
- [x] ASI:One: `@wattwisegrid price next 3 hours` answers (the task's done check)

### WattWise Events
- [x] Address: `agent1qfpewxv737laxv5gk0zcraucrdse4cwl596399ce5cruy5kmn3t3v5h262y`
- [x] Running; log shows the address and the inspector link (live mode, terminal tab, 2026-10-24 local)
- [x] Inspector -> Connect -> Mailbox -> Finish; log: "Successfully registered as mailbox agent in Agentverse", "Registration on Almanac API successful"
- [x] Profile name **WattWise Events**, handle `@wattwiseevents`, README `README_events.md` (badges + address visible)
- [x] Category: Innovation Lab (README badges, see above); Discovery -> My Keywords: events nearby, local events, crowd,
  expected attendance
- [x] Protocols: `wattwise-events` 0.1.0 + AgentChatProtocol 0.3.0
- [x] Starter prompts: "events tonight", "any big events nearby in the next 6 hours?"
- [x] Index shows **active** (`last_updated` 2026-10-25 00:33:21 UTC, `type: uagent`, see note below); profile URL https://agentverse.ai/agents/details/agent1qfpewxv737laxv5gk0zcraucrdse4cwl596399ce5cruy5kmn3t3v5h262y/profile
- [x] ASI:One: `@wattwiseevents events tonight` answers (recorded data, labeled `recorded`)

- Category line stays open: the README badges + address are published (index `readme` starts with
  `![tag:innovationlab]` and contains the address), but keywords are not set in Discovery -> My Keywords yet
- Starter prompts and the ASI:One `@handle` checks stay open (set / test in the Agentverse and ASI:One UIs)

### Index + mailbox check (2026-10-25 00:35 UTC)
- `GET /v1/search/agents/<address>` for all three: name, handle, description, README (badges + address line), protocols
  (own 0.1.0 + AgentChatProtocol 0.3.0), `status: active`, `category: community`, `system_wide_tags: []`, 0 interactions
- `type` shows `uagent`, not `mailbox` (the Concierge showed the same right after its first Connect). Messages do go through
  the mailbox: a local probe agent (scratchpad `probe_public.py`) sent one chat to each and got an ack + reply in seconds:
  Grid `live_api` CAISO NP15 3 h, Weather `live_api` Berkeley 3 h, Events `recorded` Giants vs Dodgers. If `type` is still
  `uagent` later: open the inspector, check the connection says Mailbox (switch from "Uagent" if needed)
- Logs: Events' first Connect hit `WinError 121` (network timeout) and the retry succeeded; Weather logged one
  `getaddrinfo failed` on the mailbox poll and kept running. Both were the local network, not the agents

- [ ] All four names + addresses + handles sent to Kritazya for README.md
- If a handle is taken, Agentverse rejects it on Connect: set `<NAME>_AGENT_HANDLE` in `agents/.env`, restart, Connect again,
  and update the README's `**Agent:**` line

## Check 2026-10-24 19:00 local (via the browser)
- Keywords set in Discovery -> My Keywords for Weather (5), Grid (5), Events (4); starter prompts saved (3 each)
- Published READMEs fixed on Agentverse: no more mojibake; Concierge README replaced with the current file (address line + paid plan)
- Innovation Lab: both badges render on all four profiles; README has name + address (hackpack rule). Index category stays community
- ASI:One via asi1.ai/ai/<address>: Grid answered (live_api CAISO NP15), Weather answered (live_api Berkeley), Events answered (recorded Giants game)
- ASI:One handle search does not list the three specialists yet (only @wattwise); use the asi1.ai/ai/<address> page or Agentverse Chat with Agent
- Concierge: ASI:One says "WattWise Concierge isn't in this chat, so it won't reply" (with @wattwise and with the address); Invite to chat and Talk to did not fix it. Cause: the Concierge was not running. 19:12 retest with it running: it answered in ASI:One ("I can't reach the kitchen right now" = backend not reachable yet)
