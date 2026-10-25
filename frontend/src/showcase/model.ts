// Showcase model: a deliberately small, seeded model of the Demo Café on a Friday dinner rush, for the public demo
// page. Two lanes share the same customers: "without" runs every appliance as asked, "with" runs a simple rule-based
// controller inside the owner's rules. It is NOT the WattWise engine and never talks to the backend; it only feeds the
// 3D floor with TickState-shaped data so the page runs anywhere. Ratings and limits match the Demo Café fixture.
import type { DeviceState, HubDeviceReading, Lane, TickState } from "@/types";

export const START_MIN = 17 * 60; // 5:00 PM
export const END_MIN = 21 * 60; // 9:00 PM
const BLOCK_MIN = 15;
const DECIDE_EVERY_MIN = 5;
const CAP_KW = 40;
// demo_tariff_v1 (illustrative): $20/kW monthly max + $8/kW peak-period max; peak energy $0.38/kWh.
export const DEMAND_USD_PER_KW = 20 + 8;
export const ENERGY_USD_PER_KWH = 0.38;
const DAY = "2026-07-17";

type Model = "cook" | "hvac" | "cycle" | "job" | "fixed";
interface Spec {
  id: string;
  name: string;
  type_id: string;
  importance: "always_on" | "flexible" | "deferrable";
  rated_kw: number;
  model: Model;
  idle_kw?: number;
  kw_per_order?: number;
  duty_idle_pct?: number;
  duty_busy_pct?: number;
  min_power_pct?: number;
  max_reduce_min?: number;
  cycle_min?: number;
  max_delay_min?: number;
}

const SPECS: Spec[] = [
  { id: "hvac_1", name: "HVAC 1", type_id: "hvac", importance: "flexible", rated_kw: 8, model: "hvac", min_power_pct: 40, max_reduce_min: 30 },
  { id: "hvac_2", name: "HVAC 2", type_id: "hvac", importance: "flexible", rated_kw: 8, model: "hvac", min_power_pct: 40, max_reduce_min: 30 },
  { id: "walk_in_cooler_1", name: "Walk-in cooler 1", type_id: "walk_in_cooler", importance: "flexible", rated_kw: 3.5, model: "cycle", duty_idle_pct: 33, duty_busy_pct: 67 },
  { id: "reach_in_fridge_1", name: "Reach-in fridge 1", type_id: "reach_in_fridge", importance: "always_on", rated_kw: 0.8, model: "cycle", duty_idle_pct: 23, duty_busy_pct: 57 },
  { id: "freezer_1", name: "Freezer 1", type_id: "freezer", importance: "always_on", rated_kw: 1.4, model: "cycle", duty_idle_pct: 24, duty_busy_pct: 48 },
  { id: "ice_machine_1", name: "Ice machine 1", type_id: "ice_machine", importance: "deferrable", rated_kw: 1.6, model: "job", cycle_min: 20, max_delay_min: 60 },
  { id: "fryer_1", name: "Fryer 1", type_id: "fryer", importance: "always_on", rated_kw: 14, model: "cook", idle_kw: 1.5, kw_per_order: 0.26 },
  { id: "oven_1", name: "Oven 1", type_id: "oven", importance: "always_on", rated_kw: 10, model: "cook", idle_kw: 2, kw_per_order: 0.12 },
  { id: "grill_1", name: "Grill 1", type_id: "grill", importance: "always_on", rated_kw: 8, model: "cook", idle_kw: 1.5, kw_per_order: 0.12 },
  { id: "dishwasher_1", name: "Dishwasher 1", type_id: "dishwasher", importance: "deferrable", rated_kw: 6, model: "job", cycle_min: 30, max_delay_min: 60 },
  { id: "water_heater_1", name: "Water heater 1", type_id: "water_heater", importance: "flexible", rated_kw: 4.5, model: "cycle", duty_idle_pct: 25, duty_busy_pct: 67, min_power_pct: 40, max_reduce_min: 30 },
  { id: "lights_1", name: "Lights 1", type_id: "lights", importance: "always_on", rated_kw: 2.4, model: "fixed" },
];
const SPEC = Object.fromEntries(SPECS.map((s) => [s.id, s]));
const JOBS = ["dishwasher_1", "ice_machine_1"];
// Flexible devices the controller may trim, in order. Refrigeration is never trimmed here (food safety first).
const TRIM_ORDER = ["hvac_1", "hvac_2", "water_heater_1"];
const COOLDOWN_MIN = 15;
const MARGIN_KW = 0.3;

interface DeviceSim {
  kw: number;
  state: DeviceState;
  cap_pct: number;
  trim_until: number | null;
  cooldown_until: number | null;
  waiting_since: number | null;
  job_left: number;
}

export interface LaneSim {
  lane: Lane;
  devices: Record<string, DeviceSim>;
  indoor_c: number;
  racks: number;
  ice_pct: number;
  kw: number;
  block_start: number;
  block_kwh: number;
  peak_kw: number;
  energy_kwh: number;
  recent_kw: number[];
}

export interface ShowcaseSim {
  t: number;
  done: boolean;
  customers_per_hour: number;
  orders: number;
  outdoor_c: number;
  rand: () => number;
  lanes: Record<Lane, LaneSim>;
}

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

function newLane(lane: Lane): LaneSim {
  const devices: Record<string, DeviceSim> = {};
  for (const s of SPECS) {
    devices[s.id] = { kw: 0, state: "off", cap_pct: 100, trim_until: null, cooldown_until: null, waiting_since: null, job_left: 0 };
  }
  return { lane, devices, indoor_c: 22.6, racks: 2, ice_pct: 70, kw: 0, block_start: START_MIN, block_kwh: 0, peak_kw: 0, energy_kwh: 0, recent_kw: [] };
}

export function createShowcase(seed = 7): ShowcaseSim {
  return {
    t: START_MIN, done: false, customers_per_hour: 0, orders: 0, outdoor_c: 27, rand: mulberry32(seed),
    lanes: { without: newLane("without"), with: newLane("with") },
  };
}

function power(sim: ShowcaseSim, lane: LaneSim, s: Spec, d: DeviceSim): number {
  const busy = clamp(sim.customers_per_hour / 120, 0, 1);
  let want: number;
  d.state = "on";
  if (s.model === "cook") want = Math.min(s.rated_kw, s.idle_kw! + s.kw_per_order! * sim.orders);
  else if (s.model === "hvac") want = s.rated_kw * clamp(0.35 + (lane.indoor_c - 22.5) * 0.6, 0.15, 1);
  else if (s.model === "cycle") want = (s.rated_kw * (s.duty_idle_pct! + (s.duty_busy_pct! - s.duty_idle_pct!) * busy)) / 100;
  else if (s.model === "job") {
    want = d.job_left > 0 ? s.rated_kw : 0;
    d.state = d.job_left > 0 ? "running_job" : d.waiting_since != null ? "waiting" : "off";
  } else want = s.rated_kw;
  if (d.cap_pct < 100) {
    want = Math.min(want, (s.rated_kw * d.cap_pct) / 100);
    d.state = "reduced";
  }
  return want;
}

function startJob(lane: LaneSim, id: string) {
  lane.devices[id].waiting_since = null;
  lane.devices[id].job_left = SPEC[id].cycle_min!;
}

function jobs(sim: ShowcaseSim, lane: LaneSim) {
  // Dirty racks and the ice bin decide when a job is ready; "without" starts at once, "with" lets the controller decide.
  lane.racks += (sim.customers_per_hour / 60) * 0.12;
  lane.ice_pct = clamp(lane.ice_pct - (sim.customers_per_hour / 60) * 0.25, 0, 100);
  for (const id of JOBS) {
    const d = lane.devices[id];
    if (d.job_left > 0) {
      d.job_left -= 1;
      if (d.job_left === 0) {
        if (id === "dishwasher_1") lane.racks = Math.max(0, lane.racks - 8);
        else lane.ice_pct = clamp(lane.ice_pct + 45, 0, 100);
      }
      continue;
    }
    const ready = id === "dishwasher_1" ? lane.racks >= 8 : lane.ice_pct < 55;
    if (!ready) continue;
    if (lane.lane === "without") startJob(lane, id);
    else if (d.waiting_since == null) d.waiting_since = sim.t;
    else if (sim.t - d.waiting_since >= SPEC[id].max_delay_min!) startJob(lane, id); // the owner's max delay
  }
}

function controller(sim: ShowcaseSim, lane: LaneSim) {
  const t = sim.t;
  // Trims end at the owner's max_reduce_min, then a cooldown before the device can be trimmed again.
  for (const id of TRIM_ORDER) {
    const d = lane.devices[id];
    if (d.trim_until != null && t >= d.trim_until) Object.assign(d, { cap_pct: 100, trim_until: null, cooldown_until: t + COOLDOWN_MIN });
  }
  if ((t - START_MIN) % DECIDE_EVERY_MIN !== 0) return;

  // Look a little ahead: the rush builds, so add the last 10 minutes' rise.
  const past = lane.recent_kw.length > 10 ? lane.recent_kw[lane.recent_kw.length - 11] : lane.kw;
  const rising = Math.max(0, (lane.kw - past) / 10);
  const elapsed = t - lane.block_start + 1;
  const projected = (lane.block_kwh + (lane.kw * (BLOCK_MIN - elapsed)) / 60) / (BLOCK_MIN / 60);
  let risk = Math.max(projected, lane.kw + rising * DECIDE_EVERY_MIN);
  const waiting = JOBS.filter((id) => lane.devices[id].waiting_since != null);

  if (risk > CAP_KW - MARGIN_KW) {
    for (const id of TRIM_ORDER) {
      if (risk <= CAP_KW - MARGIN_KW) break;
      const d = lane.devices[id];
      const s = SPEC[id];
      if (d.cap_pct < 100 || (d.cooldown_until != null && t < d.cooldown_until)) continue;
      const saves = d.kw - (s.rated_kw * s.min_power_pct!) / 100;
      if (saves <= 0.1) continue;
      Object.assign(d, { cap_pct: s.min_power_pct!, trim_until: t + s.max_reduce_min! });
      risk -= saves;
    }
    return; // waiting jobs stay held
  }
  // Room under the cap: start held jobs first, then lift one trim (assume a full rebound: energy is moved, not deleted).
  let room = CAP_KW - MARGIN_KW - risk;
  for (const id of waiting) {
    if (SPEC[id].rated_kw <= room) {
      startJob(lane, id);
      room -= SPEC[id].rated_kw;
    }
  }
  for (const id of TRIM_ORDER) {
    const d = lane.devices[id];
    if (d.cap_pct < 100 && SPEC[id].rated_kw - d.kw <= room - 1) {
      Object.assign(d, { cap_pct: 100, trim_until: null, cooldown_until: t + COOLDOWN_MIN });
      break;
    }
  }
}

function meter(sim: ShowcaseSim, lane: LaneSim) {
  if (sim.t - lane.block_start >= BLOCK_MIN) {
    lane.peak_kw = Math.max(lane.peak_kw, lane.block_kwh / (BLOCK_MIN / 60));
    lane.block_start += BLOCK_MIN;
    lane.block_kwh = 0;
  }
  lane.block_kwh += lane.kw / 60;
  lane.energy_kwh += lane.kw / 60;
}

/** Advance one simulated minute. */
export function stepShowcase(sim: ShowcaseSim) {
  if (sim.done) return;
  const t = sim.t;
  // Shared, seeded customers: the dinner rush peaks around 7 PM.
  const rush = 80 * Math.exp(-(((t - 19 * 60) / 55) ** 2));
  sim.customers_per_hour = (30 + rush) * (0.94 + sim.rand() * 0.12);
  sim.orders += (sim.customers_per_hour * 0.25 - sim.orders) * 0.15;
  sim.outdoor_c = 27 - ((t - START_MIN) / (END_MIN - START_MIN)) * 5;
  for (const lane of [sim.lanes.without, sim.lanes.with]) {
    jobs(sim, lane);
    lane.kw = 0;
    for (const s of SPECS) {
      const d = lane.devices[s.id];
      d.kw = power(sim, lane, s, d);
      lane.kw += d.kw;
    }
    const hvac = lane.devices.hvac_1.kw + lane.devices.hvac_2.kw;
    lane.indoor_c = clamp(lane.indoor_c + (sim.outdoor_c - lane.indoor_c) * 0.01 + sim.orders * 0.0025 + 0.012 - hvac * 0.0075, 18, 30);
    meter(sim, lane);
    lane.recent_kw.push(lane.kw);
    if (lane.recent_kw.length > 20) lane.recent_kw.shift();
    if (lane.lane === "with") controller(sim, lane);
  }
  sim.t += 1;
  if (sim.t >= END_MIN) {
    for (const lane of [sim.lanes.without, sim.lanes.with]) meter(sim, lane); // close the last block
    sim.done = true;
  }
}

/** The running 15-minute average of the block in progress. */
export function blockAvgKw(lane: LaneSim, t: number): number {
  return lane.block_kwh / (Math.max(1, t - lane.block_start) / 60);
}

/** Tonight's highest 15-minute average so far, counting the block in progress. */
export function peakSoFarKw(sim: ShowcaseSim, lane: LaneSim): number {
  return Math.max(lane.peak_kw, sim.done ? 0 : blockAvgKw(lane, sim.t));
}

const iso = (min: number) => `${DAY}T${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}:00`;

/** One lane as the TickState shape the 3D floor reads (hub readings, customers, meter). */
export function toTick(sim: ShowcaseSim, laneName: Lane): TickState {
  const lane = sim.lanes[laneName];
  const devices: HubDeviceReading[] = SPECS.map((s) => {
    const d = lane.devices[s.id];
    return {
      device_id: s.id, type_id: s.type_id, name: s.name, importance: s.importance, state: d.state,
      power_kw: Math.round(d.kw * 10) / 10, rated_kw: s.rated_kw, power_pct: Math.round((d.kw / s.rated_kw) * 100), source: "simulated",
      ...(s.model === "hvac" ? { physical: { indoor_temp_c: Math.round(lane.indoor_c * 10) / 10 } } : {}),
    } as HubDeviceReading;
  });
  return {
    lane: laneName,
    ts: iso(sim.t),
    hub: { hub_id: "showcase", lane: laneName, tick_id: sim.t - START_MIN, ts: iso(sim.t), total_kw: lane.kw, customers_per_hour: sim.customers_per_hour, devices, acks: [], source: "simulated" },
    meter: { block_avg_kw: blockAvgKw(lane, sim.t), target_kw: CAP_KW, peak_cap_kw: CAP_KW, total_kw: lane.kw },
    customers_per_hour: Math.round(sim.customers_per_hour),
    new_decisions: [],
    forecast_kw: null,
  } as unknown as TickState;
}

export const CAP = CAP_KW;
