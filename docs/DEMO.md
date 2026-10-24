# Demo (3 min pitch + 2 min Q&A)

## Demo mode
`DEMO_MODE=1`: fixed seed, preset "Demo Café" kitchen, Friday 11:30, speed 120×, cached backtest,
AI explanations live if they arrive within 3 s (else template), recorded video as final fallback.

## Script
| Time | What |
|---|---|
| 0:00–0:20 | Story: one 15-minute lunch spike sets a café's whole month of demand charges. |
| 0:20–0:40 | Problem: owners don't know; tools only show charts or say "turn things off". |
| 0:40–1:00 | Builder: show the kitchen, importance per device, peak cap 40 kW. Everything reports to one hub. |
| 1:00–1:50 | Live: judge clicks +40 customers. Without lane breaks the cap; With lane stays under. Feed: "Delayed dishwasher 20 min", "HVAC to 60% for 15 min". One approval → judge approves. |
| 1:50–2:20 | Proof: 12 months of DOE-calibrated restaurant data on a real tariff, no peeking: Without [$A] · Timer [$B] · With [$C]; worst case still saves [$D]. |
| 2:20–2:45 | How: the engine decides and executes; Claude only explains and never does the math. |
| 2:45–3:00 | "WattWise: stop paying for peaks you never saw coming." |
Fill brackets only with numbers on screen.

## Likely questions
- Does the AI make the decisions? No — the engine does; it runs the same with the AI off.
- Does the backtest see the future? No — rows are fed one at a time; a test enforces it.
- Is this real data? Calibrated DOE restaurant models, plus (if done) real metered food-service buildings.
- Why not a timer? The timer is our baseline, chosen as the best schedule from the previous month, and we beat it.
- Does it work with real hardware? Every device reports to one hub with the same interface a real ESP32 would use.
