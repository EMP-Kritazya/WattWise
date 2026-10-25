/* eslint-disable */
/**
 * Generated `api` utility.
 *
 * THIS CODE IS AUTOMATICALLY GENERATED.
 *
 * To regenerate, run `npx convex dev`.
 * @module
 */

import type * as backtest from "../backtest.js";
import type * as batch from "../batch.js";
import type * as bills from "../bills.js";
import type * as commands from "../commands.js";
import type * as contextSnapshots from "../contextSnapshots.js";
import type * as crons from "../crons.js";
import type * as decisions from "../decisions.js";
import type * as deviceBlocks from "../deviceBlocks.js";
import type * as devices from "../devices.js";
import type * as escalations from "../escalations.js";
import type * as hubs from "../hubs.js";
import type * as kitchens from "../kitchens.js";
import type * as liveness from "../liveness.js";
import type * as proposals from "../proposals.js";
import type * as validators from "../validators.js";
import type * as writes from "../writes.js";

import type {
  ApiFromModules,
  FilterApi,
  FunctionReference,
} from "convex/server";

declare const fullApi: ApiFromModules<{
  backtest: typeof backtest;
  batch: typeof batch;
  bills: typeof bills;
  commands: typeof commands;
  contextSnapshots: typeof contextSnapshots;
  crons: typeof crons;
  decisions: typeof decisions;
  deviceBlocks: typeof deviceBlocks;
  devices: typeof devices;
  escalations: typeof escalations;
  hubs: typeof hubs;
  kitchens: typeof kitchens;
  liveness: typeof liveness;
  proposals: typeof proposals;
  validators: typeof validators;
  writes: typeof writes;
}>;

/**
 * A utility for referencing Convex functions in your app's public API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = api.myModule.myFunction;
 * ```
 */
export declare const api: FilterApi<
  typeof fullApi,
  FunctionReference<any, "public">
>;

/**
 * A utility for referencing Convex functions in your app's internal API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = internal.myModule.myFunction;
 * ```
 */
export declare const internal: FilterApi<
  typeof fullApi,
  FunctionReference<any, "internal">
>;

export declare const components: {};
