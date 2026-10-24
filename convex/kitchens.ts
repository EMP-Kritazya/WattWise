// kitchens:record (API on POST /api/kitchen). Table in CONTRACTS.md §6; the function name is not (contract question).

import { mutation } from "./_generated/server";
import { args, recordKitchen } from "./writes";

export const record = mutation({ args: args["kitchens:record"], handler: recordKitchen });
