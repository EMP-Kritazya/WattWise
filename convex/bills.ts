// bills:save (runtime at month end and on demand). CONTRACTS.md §6.

import { mutation } from "./_generated/server";
import { args, saveBill } from "./writes";

export const save = mutation({ args: args["bills:save"], handler: saveBill });
