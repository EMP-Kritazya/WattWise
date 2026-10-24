# Demo: 2 min table pitch (live) + 3 to 5 min video

## Judging logistics (Cal Hacks 13.0 hacker guide)
- Devpost submission deadline **9:00 AM Sunday**. We submit by 8:30. Devpost draft goes in Saturday night.
- Table numbers are assigned after 9:00. Be at the table by **10:30**; judging runs 10:30 to 12:30.
- The **whole team** stays at the table the full window. A **live demo** is required. Prepare a ~2 minute pitch + answers.
- Fetch.ai also needs: public repo, README with agent name + address + badges, 3 to 5 min video,
  and registration through the Cal Hacks ASI:One Submission Agent.

## Demo mode
`DEMO_MODE=1`: fixed seed, preset "Demo Café" kitchen, Friday 11:30, speed 120×, cached backtest,
AI explanations live if they arrive within 3 s (else template), recorded video as final fallback.
Live view over SpacetimeDB (`LIVE_TRANSPORT=ws` fallback). ESP32 on if healthy (`HARDWARE=esp32`), else simulated hub.
Demo laptop and ESP32 on a phone hotspot, not venue WiFi.

## Roles at the table
Suggested: Suyog drives ASI:One and the ESP32, Ashirwad drives the Live tab and hands a judge the surge phone,
Kritazya pitches and takes the Proof questions. Everyone can answer any question below.

## Table pitch (~2 min)
| Time | Beat | On screen | For |
|---|---|---|---|
| 0:00 to 0:20 | **Pain** | Last month's bill: one 15-minute lunch spike set most of the demand charge. | Anthropic, Microsoft |
| 0:20 to 0:45 | **Ask** | In ASI:One the owner asks "What will lunch cost me?" Forecast and the plan come back. | Fetch.ai, Anthropic |
| 0:45 to 1:05 | **Approve** | Owner says "approve it". The real fan on the ESP32 switches; the Live tab lanes split. | Convex, Fetch.ai, Hardware |
| 1:05 to 1:30 | **Judges play** | Judge taps +40 customers on their own phone; same kitchen everywhere. Without lane breaks the cap, With lane bends under it. | SpacetimeDB |
| 1:30 to 1:50 | **Proof** | 12 months of DOE-calibrated restaurant data on a real tariff, no peeking: Without [$A] · Timer [$B] · With [$C]; worst case [$D]. Running on Azure. | Microsoft, Technically Complex |
| 1:50 to 2:00 | **Close** | "WattWise: stop paying for peaks you never saw coming." | |
Fill brackets only with numbers on screen, cleared by `backtest-auditor`.

## Video (3 to 5 min, recorded in Phase 5)
1. 0:00 Problem and who it is for (independent restaurants on a demand-charge tariff).
2. 0:30 **ASI:One first**: ask, forecast, plan, approve, undo, "never touch the walk-in after 9 PM" → confirm.
3. 2:00 Live tab: two lanes, decision feed with explanations, judge surge from a second device.
4. 3:00 ESP32 receiving a command through Convex; fail safe when WiFi drops.
5. 3:30 Proof tab, checks, worst case. Architecture slide (Fetch.ai, Claude, SpacetimeDB, Convex, Azure).
6. 4:30 Where Claude could go wrong and how we guard it (no numbers from the model, owner confirms every change).

## Likely questions
- Does the AI make the decisions? No. The engine does, and it runs the same with the AI off. The AI only proposes; the owner confirms.
- Does the backtest see the future? No. Rows are fed one at a time; a test enforces it.
- Is this real data? Calibrated DOE restaurant models (NREL ComStock) on a real named tariff. January is partial (warm-up).
- Why not a timer? The timer is our baseline, chosen as the best schedule from the previous month, and we beat it.
- Does it work with real hardware? Yes, for low-voltage stand-in loads: the ESP32 gets commands pushed through Convex. Real appliances would use off-the-shelf smart relays on the same interface.
- Why two databases? Each owns one job: SpacetimeDB is the live shared kitchen, Convex holds records and devices. Nothing is stored in both.
- What if the internet drops? The ESP32 returns every load to normal after 30 s without contact; the dashboard falls back to a local transport.
- Who is it for, and where could Claude go wrong? Independent restaurant owners paying demand charges. Claude could misstate a number or act without consent, so it can quote only tool results and every change needs the owner's confirmation.
