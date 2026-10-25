// decisions:record (runtime, batched once per real second). CONTRACTS.md §6. Upsert by decision_id (an undo re-records it).

import { mutation } from "./_generated/server";
import { args, recordDecisions } from "./writes";

export const record = mutation({ args: args["decisions:record"], handler: recordDecisions });
