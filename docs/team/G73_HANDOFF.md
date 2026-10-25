# G73 integration handoff — 2026-10-25

Draft team notice; not sent. Suyog's API, runtime, Claude/Fetch.ai, store, Convex and firmware code were not changed.

The engine now exposes the owner-out escalation contract in CONTRACTS.md §1/§3. It ranks 1–3 alternatives,
applies the best within authority immediately (otherwise accept_overrun), records Claude attempt verdicts,
and allows one retry before the simulated deadline. An accepted choice queues commands for the next step.
The owner retains manual command/undo. There is no ask_owner option, awaiting_owner status, owner resolve
Proposal/tool or POST escalation resolve endpoint.

Suyog's next integration work, when authorized:

- Pass every new/changed engine escalation to live.publish_escalation(escalation, explanation, source) and viewer ws
  `{type: "escalation", data, explanation, explanation_source}`. Sources are ai or template.
- Ask Claude asynchronously with all ranked options (including outside-authority flags), Fetch.ai context and preferences.
  Call Kitchen.resolve_escalation(id, option_id, "claude", rationale). Read claude_attempts to explain acceptance/rejection;
  retry outside_authority once before deadline. Never pause or slow the clock. Timeout/off → engine fallback + template notice.
- Do not expose the removed owner-resolution route, tool or Proposal kind. Existing manual command/undo remain.
- Keep hub acknowledgements in the next HubReport; deliver every TickState.new_commands exactly once on the next sim_tick.
- Regenerated fixtures cover open, accepted, rejected and expired flows, live columns and viewer notices.

Frontend health support is retained. SpacetimeDB reducer tests and TypeScript typecheck run locally;
`spacetime build` and generated bindings must be checked with the CLI installed before deployment.

The engine remains power-only: indoor-temperature projections are null. The pre-existing 22.5°C fallback for a
kitchen with no thermal reading remains a documented stub. No savings claims or deployments are authorized here.

Validation checkpoint:

- Final engine + live suite: 310 passed, 13 skipped (existing design/dataset skips).
- Broader engine + live + backtest run: 318 passed, 15 skipped before the final control reconciliation refinements;
  those refinements are covered by the final engine/live run above.
- Frontend: 23 tests passed; production build passed with the existing bundle-size warning.
- SpacetimeDB: 14 reducer tests passed; TypeScript typecheck passed. CLI build could not start: spacetime not installed.
- Full fixture check passed: 202 files, 2,093,547 values; deterministic regeneration, multi-day equality and Pydantic validation.
- Generated ws schema check and git diff whitespace check passed. No commits were created; starting HEAD remains b23923a.
