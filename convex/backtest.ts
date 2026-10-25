// backtest:save (API after run_backtest). CONTRACTS.md §6. One backtest_results row per BacktestResult + run_id.

import { mutation } from "./_generated/server";
import { args, saveBacktest } from "./writes";

export const save = mutation({ args: args["backtest:save"], handler: saveBacktest });
