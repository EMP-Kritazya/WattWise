# Live screen design: chosen direction (Demo Café · Toy Box)

**Chosen by Ashirwad on Oct 24.** It replaces the earlier concepts (glass ceiling, power rivers and so on), which are dropped.
The reference mockup is `frontend/design/toybox-restaurant-mockup.html` (open it in a browser); it is a static SVG drawing of the target.

**In one line:** the **whole restaurant** in the current layout, restyled as a **toy-like miniature with ink outlines**, plus:
- one gauge (With needle under the cap, Without as a ghost needle);
- the **demand-charge card** (Without "+$67.20", With "$0 extra");
- one Claude card.

Calm and simple: one thing happening at a time.

## Rules that still apply
- Every number on screen comes from the engine (SpacetimeDB rows or the fixtures). The browser formats it; it never computes it.
- Lane colours, honest labels ("simulated") and `useDevices()` / `useLive()` keep the meanings they have in UI.md.
- Scope stays inside `frontend/`. Keep the existing 3D floor code and its features; this is a restyle plus a few overlays.

## 1. The 3D restaurant (restyle the existing floor)
**Layout:** keep `plan.ts` exactly as it is: kitchen, cold storage, dish room, office with the hub, dining room with the bar and tables, and roof units.

**Look:**
- **Palette:**

  | Part | Colours |
  |---|---|
  | Background | `#FFF6E9` |
  | Building slab | `#E8B89A` |
  | Back walls | `#FFF1E2` (light blue windows) |
  | Low inner walls | `#FFE7D1` |
  | Kitchen floor | checker `#F7D9C4` / `#F1C9AE` |
  | Cold storage floor | checker `#DCEBF7` / `#CDE0F1` |
  | Dish room floor | checker `#DDF2E3` / `#CBE8D4` |
  | Office floor | checker `#EADFF6` / `#E2D4F2` |
  | Dining floor | planks `#F3D3A6` |
  | Ink outlines | `#22223B` |

- **Materials:** `MeshToonMaterial` with a 3-step `gradientMap` and drei `<Outlines thickness≈0.02 color="#22223B">` on every object. Rounded edges (`RoundedBox`). No bloom on the scenery.
- **Lighting:** one warm key light with soft shadows (`AccumulativeShadows` or `ContactShadows`) and a light ambient. No coloured light effects.
- **Camera:** the fixed isometric view, framed so the whole restaurant fills the stage. No auto camera moves during the demo.

**Appliances** must be recognisable, each in its own pastel:

| Appliance | Colour | Detail |
|---|---|---|
| Fryer | `#FFB4A2` | two oil baskets |
| Grill | `#FFD6A5` | four burner rings |
| Oven | `#E5989B` | glowing window |
| Reach-in | `#BDE0FE` | glass door |
| Walk-in | `#A9D6F5` | door and handle |
| Freezer | `#C3CEF6` | |
| Dishwasher | `#A2D2FF` | door with handle |
| Water heater | `#FFC8DD` | cylinder |
| Ice machine | `#CDEAC0` | bin |
| HVAC | `#E9EDC9` | fan on top, on the roof pad |

**Dining room:**
- Small wooden tables with chair blocks, a warm glow under each table for the lights device, and toy diners: a coloured block body with a round head.
- More diners appear as customers rise, and guests queue at the door after "+40 customers".
- **Hub:** the black box on the office desk with a teal LED. Cables run on the floor from the hub to every appliance.

## 2. Appliance states (on the appliance itself)
| State | Look |
|---|---|
| Running | full pastel colour, small red LED, working detail lit (burners, oil, oven window) |
| Reduced by WattWise | teal `#2EC4B6` ring on the floor, teal outline, teal LED, cable to the hub turns teal and dashed |
| Held (waiting) | colour faded toward grey, dashed amber `#FFB703` ring, white clock badge above it |
| Off | plain grey `#D9D4CC`, no LED |

**When WattWise changes something:** everything it didn't touch fades about 30% toward the background, and the changed appliances get the outline and a pinned label for a few seconds. One change at a time.

**Pinned labels** are museum-style white cards with a coloured side bar, joined by a line to the appliance, e.g.:
- "Dishwasher held 20 min · −6 kW · still done by 9:30"
- "HVAC 1 + 2 turned to 45% · Dining room stays 23 °C"

## 3. Screen layout (16:9)
- **Stage (left ~73%):** the restaurant.
  - **Top-left:** "Demo Café" (Fredoka 700), then the clock line (Nunito): "Fri 6:42 PM · simulated · Marina, San Francisco".
  - **After a surge:** a dark pill under the clock: "+40 customers from Table 3".
- **Right column (~25%):** three white cards with ink outlines and 22 px corners.
  1. **15-minute peak gauge:** a semicircle with a red zone from the cap upward and a "cap 40" mark. The solid ink needle is With; the grey dashed ghost needle is Without. The big number is With's kW.
  2. **This month's demand charge:**
     - a red-tinted row: "WITHOUT · new peak 47.5 kW" with **+$67.20** big;
     - a teal-tinted row: "WITH · held at 37.9 kW" with **$0 extra**.
  3. **Claude card** (teal fill): "Claude chose 3 of 3" plus one sentence. It shows "Claude is choosing…" while the escalation is open.
- **Fonts:** Fredoka (headings, numbers) and Nunito (body), both on Google Fonts.

**Hidden on this screen during the demo:** the debug text in the sidebar and the repeated KPI cards. The decision feed and charts stay in the Charts view.

## 4. Where the numbers come from
| On screen | Source |
|---|---|
| Gauge needles | `live_tick.block_avg_kw` per lane; cap from `live_tick.target_kw` |
| "+$67.20" | the open or latest escalation's `accept_overrun` option, `projected.cost_delta_usd` (67.20 in the fixtures) |
| "$0 extra" | the chosen option's `projected.cost_delta_usd` |
| Claude card | `live_escalation`: status, `chosen_option_id`, rationale |
| Pinned labels | the Decision rows in `live_feed` (action, value, `effect`) and the device's physical gauge |

**Contract question for Kritazya:** without an escalation, there is no field for "this month's demand charge so far" per lane. The card should then show only kW until he adds one. The browser must not multiply kW × $/kW.

## 5. Build order
1. Toon materials, outlines, palette and soft shadows on the existing floor (no layout change).
2. Recognisable appliance shapes and the four states.
3. Diners, guest queue and the warm table glow.
4. The right column: gauge, demand-charge card, Claude card. Then hide the debug text and the duplicate KPI cards.
5. The "fade others + pinned label" moment when WattWise acts.
