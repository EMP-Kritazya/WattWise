"""Backtest (owner: Kritazya): assumptions, the CLI that writes the DEMO_MODE cache, and the post-run checks.

The replay itself is the pure `engine.run_backtest(inputs, months, assumptions_id, on_progress)` (CONTRACTS.md section 3);
`data.backtest_inputs.load_backtest_inputs` builds its inputs (all file I/O lives in `data/` and here, never in `engine/`).
"""
