"""Data loaders (owner: Kritazya). I/O lives here, never in `engine/` (golden rule 7).

- `comstock.py`      NREL ComStock 15-min end-use rows -> UTC interval starts + kW per end use
- `tariff_urdb.py`   OpenEI URDB record -> the CONTRACTS.md Tariff shape (`label: "urdb"`)
- `recipe.py`        distribution recipe (DATA_AND_PROOF.md): end uses -> categories -> this kitchen's devices
- `warmup.py`        WarmUpHistory from the recipe output (the 4 weeks before a start)
- `backtest_inputs.py`  `load_backtest_inputs(months, assumptions_id)` -> BacktestInputs for `engine.run_backtest`

The raw dataset is gitignored (`dataset/`); nothing here is committed data.
"""
