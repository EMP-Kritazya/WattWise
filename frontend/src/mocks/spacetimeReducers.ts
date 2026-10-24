import { fixtureLiveRows } from "./liveRows";

export class ReducerValidationError extends Error {}

/** Fixture implementation of the public SpacetimeDB request_surge reducer. */
export async function requestSurgeReducer(customers: number, durationMin: number): Promise<void> {
  if (!Number.isInteger(customers) || customers < 1 || customers > 80) {
    throw new ReducerValidationError("customers must be an integer from 1 to 80");
  }
  if (!Number.isInteger(durationMin) || durationMin < 15 || durationMin > 120) {
    throw new ReducerValidationError("duration_min must be an integer from 15 to 120");
  }
  fixtureLiveRows.requestSurge(customers, durationMin);
}
