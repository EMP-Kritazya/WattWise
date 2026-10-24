// contextSnapshots:record (runtime, hourly: Context + ts).
// Table in CONTRACTS.md §6; the function name is not (contract question).

import { mutation } from "./_generated/server";
import { args, recordContextSnapshot } from "./writes";

export const record = mutation({ args: args["contextSnapshots:record"], handler: recordContextSnapshot });
