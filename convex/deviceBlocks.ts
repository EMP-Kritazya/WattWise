// deviceBlocks:record (runtime, every closed 15-min block, simulated and measured).
// Table in CONTRACTS.md §6; the function name is not (contract question).

import { mutation } from "./_generated/server";
import { args, recordDeviceBlocks } from "./writes";

export const record = mutation({ args: args["deviceBlocks:record"], handler: recordDeviceBlocks });
