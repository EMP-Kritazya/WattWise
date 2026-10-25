![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# WattWise Concierge: restaurant electricity bill and demand charge agent

**Agent:** WattWise Concierge · `@wattwise` · `agent1qgr6vxnyeewx8rdsxpdu896v9w8cv5q4jmf4aw4244vu2r2nhqn9zt3gdsn`

Lowers a restaurant's electricity demand charges by forecasting and shifting appliance load.

WattWise is connected to the restaurant's own kitchen. It forecasts the kitchen's next 15-minute peak power, then briefly
reduces or delays flexible appliances so the peak stays under the owner's cap without stopping service. On a commercial
utility tariff, that peak sets the demand charge, often the largest single line on a restaurant electricity bill. Ask the
Concierge about your restaurant's electricity bill, demand charges, peak power, today's forecast, or what WattWise decided
in your kitchen and why. Answers come from your kitchen's live data, not generic energy-saving tips.

## Key features

- **Peak power forecast** for your kitchen: when the next lunch or dinner rush peak will hit and how big it will be.
- **Demand charge reduction**: delays deferrable load (dishwasher, water heater, ice machine) and briefly reduces flexible
  load (HVAC, walk-in defrost) so the 15-minute peak stays under your peak cap.
- **Explains every decision**: why the dishwasher was delayed, what the kitchen would have drawn without WattWise.
- **Owner rules are hard limits**: always-on equipment is never touched, refrigeration never goes below its food-safety
  limit, delayed jobs always finish by their deadline. Change a rule from chat ("never touch the walk-in after 9 PM").
- **Live context**: weather, grid electricity prices and nearby events that bring in a crowd.
- **Savings report**: what the demand charge and energy bill would have been without WattWise.

## How to use

Send a message in plain English. The Concierge answers from your kitchen's data.

```
Input:  What will lunch cost me in power today?
Output: The forecast lunch peak (kW), the time it hits, the demand charge it would set, and what WattWise plans to shift.
```

```
Input:  Why did you delay the dishwasher?
Output: The decision, the reason, and the peak power it avoided, with the deadline the dishwasher will still finish by.
```

```
Input:  Never touch the walk-in after 9 PM
Output: A proposed rule change; reply "confirm" to apply it.
```

## Paid plan: let Claude handle tonight's decisions

On the free plan every escalation (a moment when no move inside your rules can hold the peak cap) comes to you. Say
**"Let Claude handle tonight's decisions"** to pay through Stripe (test mode) right in the chat. Once the payment
clears you get a proposal listing exactly how far Claude may go (kW over the cap, extra delay, extra reduction; never
below a device's minimum power, never past the food-safety floor). Reply "confirm" and Claude resolves the next
escalations inside those bounds; anything beyond them still comes to you. Cancel or a failed payment keeps you on the
free plan. WattWise never sees or stores card details.

## Use cases and example queries

For restaurant, cafe and commercial kitchen owners whose utility bill has a demand charge:

- My restaurant electricity bill is too high
- Why is my restaurant power bill so expensive?
- Lower my demand charges
- How do I reduce the peak demand charge for my cafe?
- What will lunch cost me in power today?
- What will the dinner rush do to my electricity peak tonight?
- How much did we save on electricity this month?
- What did you decide about tonight?
- Let Claude handle tonight's decisions
- Undo that
- Choose option 2

## Limitations

- Built for commercial kitchens on utility tariffs with a demand charge (peak power charge); not for homes or EV charging.
- Live answers need a WattWise-connected kitchen. During the hackathon that kitchen is a simulated restaurant, labeled
  simulated.
- Every number (kW, kWh, $) is computed by the WattWise engine; the language model only quotes those results.

## Metadata

WattWise team, Cal Hacks 13.0, Fetch.ai Innovation Lab. Version 0.1.
Keywords: restaurant electricity bill, restaurant energy bill, demand charge, lower demand charges, peak power, peak demand,
utility bill, commercial kitchen, cafe, kitchen energy, electricity cost, load shifting.
