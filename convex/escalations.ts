// escalations:record (runtime: final state of an Escalation, upsert by escalation_id).
// Table in CONTRACTS.md §6; the function name is not (contract question).

import { mutation } from "./_generated/server";
import { args, recordEscalation } from "./writes";

export const record = mutation({ args: args["escalations:record"], handler: recordEscalation });
