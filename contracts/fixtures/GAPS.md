# GAPS

Every gap the fixture builder found (G01–G35) now has a **demo decision** written into `docs/CONTRACTS.md`. The summary
table, with what stays open for the final design, is in `/Main_Gaps.md`. These fixtures follow those decisions, and
`check.py` enforces the ones that show up in the data:
tariff-based prices and bills, rule_break kinds and authority, default option, deadline rule, ack clamping, Proposal payloads,
the shared indoor temperature, `replay`, SpacetimeDB key/id/forecast columns, and the agent enums.

## Readings the fixtures had to choose (not fully pinned down by CONTRACTS.md)

- **Single-row `id: 0`.** §5 shows `id = 0` only on `live_context`; Main_Gaps G30 says "single-row tables". Fixtures add
  `id: 0` to `live_clock` and `live_comparison` too, including the `live_comparison` object inside the `publish_ticks` payload.
- **Per-charge demand peaks in effects.** `saving_usd` and `cost_delta_usd` charge each tariff demand charge on its own
  horizon peak (the peak-period charge only counts 16:00–21:00 blocks). Both use the single Meter `month_peak_kw` as the
  "already paid" level, because the Meter has no per-window month peak.
- **`over_max_delay` amount.** Total hold, counted from the first delay the hub applied, minus `max_delay_min`
  (here 75 − 60 = 15 min). It is checked against `max_extra_delay_min`, like `past_deadline`.
- **`explain_decision` output.** "Returns facts": fixtures return the Decision object itself.
- **Clamp limit.** `MIN_PHYSICAL_PCT = 20` is the toy simulation's physical floor, used for the clamped-ack example
  (an owner reduce to 10 % applied as 20 %). It is simulation-only, not a contract value.

## Fixture wrapper fields (not contract shapes)

`rest/*` `status`, `facade/*` `raises`, `ai_tools/*` `input_enum`, `spacetime/reducers/*` `{reducer, args}`,
`convex/functions/*` `{function, type, args, returns}` are this folder's own wrappers.
