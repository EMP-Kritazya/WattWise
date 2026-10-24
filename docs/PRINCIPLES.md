# Principles

Every design choice in WattWise follows these. If something conflicts with one, raise it before coding.

1. **Senses, judgment, reflexes.** Fetch agents sense (context). The engine reacts (all numbers, routine moves).
   Claude judges only the hard cases (escalations) and talks to the owner. Roles never blur.
2. **Numbers come from tested code.** Every user-facing number is produced by deterministic Python with a hand-computed test.
3. **The kitchen never waits.** AI and agents are asynchronous helpers with safe defaults. The engine runs identically without them.
4. **The owner holds the keys.** Importance, limits, cap and Claude's authority are owner settings. Food safety can't be overridden by anyone.
5. **One home per piece of data.** Engine memory = the simulation's truth. SpacetimeDB = what ticks (live, shared).
   Convex = records and devices (durable). Nothing is the source of truth in two places.
6. **The hub is the only door to the kitchen.** Readings out, commands in, through one interface, so a simulated hub and a
   real ESP32 are interchangeable.
7. **Contracts first, fakes first, own branches.** Each seam has a written contract and a fake; each person works on their
   branch and integrates at gates by flipping a switch.
8. **Fair proof.** Same data, tariff and loop for every policy; no peeking; all 12 months; strong baseline; worst case shown.
9. **Honest labels.** Every number shows where it came from.
10. **Safe demo.** Deploy early, demo from Azure, fall back to local transport and a recorded video, record context for demo mode.
