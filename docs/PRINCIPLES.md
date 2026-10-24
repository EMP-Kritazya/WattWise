# Principles

Every design choice in WattWise follows these. If something conflicts with one, raise it before coding.

1. **Senses, judgment, reflexes.** Fetch agents gather external context (weather, grid prices, local events). The deterministic engine computes all numerical results and routine decisions. Claude handles contextual judgment, selects among engine-generated escalation options within delegated authority, and communicates with the owner. The engine validates every selection before execution. Roles never blur.

2. **Numbers come from tested code.** Every user-facing calculated number comes from deterministic, tested code. Physical power readings originate from the simulation or real hardware. AI never invents numerical results.

3. **The kitchen never waits.** AI and external agents are asynchronous helpers. Routine engine operation never depends on their availability. Escalations have deadlines and safe defaults. Demo mode may pause simulated time for presentation purposes.

4. **The owner holds the keys.** Device importance, operating limits, demand caps, and Claude's authority are owner-defined settings. Food safety and hard physical constraints cannot be overridden by anyone.

5. **One home per piece of data.** The browser simulation (sim host tab) owns physical appliance state and power behavior. The engine owns energy, cost, forecasts, decisions, and the decision ledger. SpacetimeDB publishes shared live state. Convex stores durable records and device information. Screens only visualize SpacetimeDB state. No data has two authoritative owners.

6. **The hub is the only door to the kitchen.** Simulated devices report their readings through the hub. FastAPI carries the hub's state to the engine each tick and the engine's commands back to the hub in the next tick. The hub applies commands subject to physical constraints. The brain never directly manipulates simulated devices. Simulated and real hubs follow the same contract.

7. **Contracts first, fakes first, own branches.** Every integration seam has a written contract and a compatible fake. Teammates develop independently on their own branches and integrate through tested interfaces.

8. **Fair proof.** Baseline and optimized lanes receive identical external inputs, tariffs, and simulation rules, with independent device states. No future-data leakage. Backtests cover all 12 months where suitable historical data is available, use a credible baseline, and disclose worst-case results.

9. **Honest labels.** Every displayed number identifies its origin: simulated, measured, forecast, calculated, or estimated. Predictions and simulations are never presented as verified real-world savings.

10. **Safe demo.** Deploy early, demonstrate from Azure, retain local fallback and recorded video options, and preserve reproducible context and simulation scenarios for demo mode.
