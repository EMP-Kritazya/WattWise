// batch:apply (runtime): one real second of the runtime's writes, applied in order in one transaction, so the store makes
// one Convex call per flush instead of one per write. Each write is validated exactly like its single mutation.
// Not in CONTRACTS.md §6 yet (contract question for Kritazya).

import { v } from "convex/values";
import { mutation } from "./_generated/server";
import { args, handlers } from "./writes";

type Name = keyof typeof args;

const write = (name: Name) => v.object({ name: v.literal(name), args: v.object(args[name]) });
const names = Object.keys(args) as Name[];
const [first, second, ...rest] = names.map(write);

export const apply = mutation({
  args: { writes: v.array(v.union(first, second, ...rest)) },
  handler: async (ctx, { writes }) => {
    for (const { name, args: a } of writes) {
      await (handlers[name] as (ctx: unknown, a: unknown) => Promise<null>)(ctx, a);
    }
    return null;
  },
});
