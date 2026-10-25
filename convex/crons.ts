// Scheduled liveness (liveness.ts): stale commands → failed, offline hubs logged. Every 10 s.

import { cronJobs } from "convex/server";
import { internal } from "./_generated/api";

const crons = cronJobs();

crons.interval("liveness sweep", { seconds: 10 }, internal.liveness.sweep);

export default crons;
