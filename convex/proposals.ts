// proposals:upsert (API / agent). CONTRACTS.md §6. By proposal_id.

import { mutation } from "./_generated/server";
import { args, upsertProposal } from "./writes";

export const upsert = mutation({ args: args["proposals:upsert"], handler: upsertProposal });
