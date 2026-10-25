# Demo: 2 min table pitch (live) + 3 to 5 min video

## Judging logistics (Cal Hacks 13.0 hacker guide)
- Devpost submission deadline **9:00 AM Sunday**. We submit by 8:30. Devpost draft goes in Saturday night.
- Table numbers are assigned after 9:00. Be at the table by **10:30**; judging runs 10:30 to 12:30.
- The **whole team** stays at the table the full window. A **live demo** is required. Prepare a ~2 minute pitch + answers.
- Fetch.ai also needs: public repo, README with agent name + address + badges, 3 to 5 min video,
  and registration through the Cal Hacks ASI:One Submission Agent.

## Demo mode
`DEMO_MODE=1`: fixed seed, preset "Demo Café" kitchen (Marina, SF; all 11 catalog types, hvac × 2, dishwasher must finish by
19:30), the made-up `demo_tariff_v1` (same in every run) until the real URDB rate is chosen, Friday 17:30, hot evening, Giants game at 19:05
(recorded context), speed 120×, one escalation scripted to appear ~2 min in, cached backtest,
AI explanations live if they arrive within 3 s (else template), recorded video as final fallback.
Live view over SpacetimeDB (`LIVE_TRANSPORT=ws` fallback). The demo laptop keeps the `/sim` tab open (the sim host);
every other screen and phone is a viewer. Fake sim host (`HUB_IMPL=fake`) as the last-resort fallback. ESP32 on if healthy
(`HARDWARE=esp32`), else browser hub only.
Demo laptop and ESP32 on a phone hotspot, not venue WiFi.

## Roles at the table
Suggested: Suyog drives ASI:One and the ESP32, Ashirwad drives the Live tab and hands a judge the surge phone,
Kritazya pitches and takes the Proof questions. Everyone can answer any question below.

## Table pitch (~2 min)
| Time | Beat | On screen | For |
|---|---|---|---|
| 0:00 to 0:15 | **Pain** | Last month's bill: one 15-minute lunch spike set most of the demand charge. | Anthropic, Microsoft |
| 0:15 to 0:35 | **Senses** | Agent Network: Weather, Grid and Events agents report to the Concierge — hot evening, prices high, Giants game 1.8 km away (crowd: medium). | Fetch.ai |
| 0:35 to 1:05 | **Judges play** | Judge taps +40 customers on their own phone; same kitchen everywhere. Engine delays the dishwasher, trims HVAC. Without lane breaks the cap; With lane bends under it. | SpacetimeDB |
| 1:05 to 1:30 | **Judgment** | Escalation card: no in-rules fix left. The engine applies its safest option at once; Claude reviews the ranked options (engine numbers), keeps or switches within the owner's authority, and says why. On the phone, the owner asks ASI:One "what did you decide about tonight?" | Anthropic, Fetch.ai |
| 1:30 to 1:50 | **Proof** | 12 months of DOE-calibrated restaurant data on a real tariff, no peeking: Without [$A] · Timer [$B] · With [$C]; worst case [$D]. Running on Azure; the ESP32 fan obeys the same commands through Convex. | Microsoft, Convex, Technical |
| 1:50 to 2:00 | **Close** | "WattWise: stop paying for peaks you never saw coming." | |
Fill brackets only with numbers on screen, cleared by `backtest-auditor`.

## Video (3 to 5 min, recorded in Phase 5)
1. 0:00 Problem and who it is for (independent restaurants on a demand-charge tariff).
2. 0:30 **ASI:One first**: ask, forecast, plan, escalation choice explained, undo, "never touch the walk-in after 9 PM" → confirm.
   Agent Network: Concierge orchestrating Weather, Grid and Events agents.
3. 2:00 Live tab: two lanes, decision feed with explanations, judge surge from a second device.
4. 3:00 ESP32 receiving a command through Convex; fail safe when WiFi drops.
5. 3:30 Proof tab, checks, worst case. Architecture slide (Fetch.ai, Claude, SpacetimeDB, Convex, Azure).
6. 4:30 Where Claude could go wrong and how we guard it (no numbers from the model, owner confirms configuration proposals; code validates escalation choices).

## Likely questions
- Does the AI make the decisions? The engine makes every routine decision and computes every number. Only when no in-rules move
  can hold the cap does Claude choose among the engine's options, inside limits the owner set; outside authority the engine rejects the choice and allows one retry; the fallback stays active,
  and if nobody answers, the safe fallback the engine applied at once simply stays. The kitchen runs the same with the AI off.
- Why several agents? Each owns one live source (weather, prices, events); the Concierge orchestrates them and talks to the owner.
- Does the backtest see the future? No. Rows are fed one at a time; a test enforces it.
- Is this real data? Calibrated DOE restaurant models (NREL ComStock) on a real named tariff. January is partial (warm-up).
- Why not a timer? The timer is our baseline, chosen as the best schedule from the previous month, and we beat it.
- Does it work with real hardware? Yes, for low-voltage stand-in loads: the ESP32 gets commands pushed through Convex. Real appliances would use off-the-shelf smart relays on the same interface.
- Why two databases? Each owns one job: SpacetimeDB is the live shared kitchen, Convex holds records and devices. Nothing is stored in both.
- What if the internet drops? The ESP32 returns every load to normal after 30 s without contact; the dashboard falls back to a local transport.
- Who is it for, and where could Claude go wrong? Independent restaurant owners paying demand charges. Claude could misstate a number or overstep, so it quotes only tool results, can only pick engine-generated options inside the owner's authority, and can never cross the food-safety floor.
