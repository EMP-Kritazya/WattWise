import { ApiError } from "@/transport/errors";
import type { ConnectionStatus, Transport } from "@/transport/types";
import type {
  BacktestResult,
  Bill,
  ClockState,
  Command,
  CommandAction,
  CustomerEventRequest,
  Decision,
  DecisionStatus,
  Device,
  DeviceCommandRequest,
  DeviceState,
  EquipmentType,
  HubDeviceReading,
  Importance,
  ImportanceLimits,
  ImportanceUpdate,
  KitchenConfig,
  KitchenView,
  Lane,
  Meter,
  ReasonCode,
  SimControlRequest,
  WsMessage,
} from "@/types";
import { mockCatalog } from "./catalog";
import { mulberry32 } from "./rng";

// MOCK: an in-browser stand-in for the FastAPI server + FakeKitchen (docs/design/API.md), so the UI can be built
// before the backend exists. Every number here is invented to look plausible; nothing is engine-computed, and the
// "with" lane doesn't conserve energy. It copies demo-mode behaviour: the clock pauses while an approval is pending.

const MIN_MS = 60_000;
const BLOCK_MS = 15 * MIN_MS;
const START_MS = Date.parse("2026-07-17T18:30:00Z"); // Friday 11:30 in Los Angeles (DEMO.md)
const LA_OFFSET_MS = -7 * 3_600_000; // PDT, fine for a July mock
const ENERGY_USD_PER_KWH = 0.24;
const DEMAND_USD_PER_KW = 20.5;
const MONTH_ENERGY_USD_BEFORE_TODAY = 1_150;
const START_ENERGY_KWH_TODAY = 95;
const START_MONTH_PEAK_KW = 36;
const REPLAN_EVERY_MIN = 5;
const FIRST_APPROVAL_AT_MIN = 20;
const APPROVAL_EVERY_MIN = 30;
const ENGINE_REDUCE_MIN = 15;
const OWNER_HOLD_MIN = 30;
const AI_DELAY_MS = 1_500;

type EngineMove =
  | { kind: "reduce"; pct: number; untilMs: number }
  | { kind: "delay"; untilMs: number; owedMin: number }
  | { kind: "catch_up"; remainingMin: number };

type OwnerOverride = { kind: "off" } | { kind: "reduce"; pct: number } | { kind: "delay"; untilMs: number };

interface MockDevice {
  device_id: string;
  name: string;
  type: EquipmentType;
  importance: Importance;
  limits: ImportanceLimits;
  jobRemainingMin: number;
  nextJobMs: number;
}

interface LaneMeter {
  energyKwhToday: number;
  blockStartMs: number;
  blockSumKw: number;
  blockCount: number;
  monthPeakKw: number;
  totalKw: number;
}

const round2 = (n: number) => Math.round(n * 100) / 100;
const iso = (ms: number) => new Date(ms).toISOString();
const latency = (ms = 80) => new Promise((resolve) => setTimeout(resolve, ms));
const sumKw = (rs: HubDeviceReading[]) => round2(rs.reduce((s, r) => s + r.power_kw, 0));
const cycleMin = (t: EquipmentType) => Number(t.params.cycle_min ?? 30);

function limit(limits: ImportanceLimits, key: string, fallback: number): number {
  const v = (limits as Record<string, unknown>)[key];
  return typeof v === "number" ? v : fallback;
}

function localHour(ms: number): number {
  const d = new Date(ms + LA_OFFSET_MS);
  return d.getUTCHours() + d.getUTCMinutes() / 60;
}

function hhmm(s: string): number {
  const [h, m] = s.split(":").map(Number);
  return h + (m || 0) / 60;
}

/** Synthetic customers/hour: lunch peak ~12:00–13:30, dinner peak ~18:30–20:30 (SIMULATION.md). */
function profileCustomersPerHour(hour: number): number {
  const bump = (mu: number, sigma: number) => Math.exp(-0.5 * ((hour - mu) / sigma) ** 2);
  return 15 + 55 * bump(12.75, 0.6) + 65 * bump(19.5, 0.8);
}

const freshMeter = (): LaneMeter => ({
  energyKwhToday: START_ENERGY_KWH_TODAY,
  blockStartMs: Math.floor(START_MS / BLOCK_MS) * BLOCK_MS,
  blockSumKw: 0,
  blockCount: 0,
  monthPeakKw: START_MONTH_PEAK_KW,
  totalKw: 0,
});

class MockServer implements Transport {
  readonly kind = "mock" as const;

  private listeners = new Set<(msg: WsMessage) => void>();
  private config: KitchenConfig | null = null;
  private devices: MockDevice[] = [];
  private rng = mulberry32(42);
  private simMs = START_MS;
  private playing = false;
  private speed = 120;
  private pausedReason: string | null = null;
  private timer: ReturnType<typeof setInterval> | undefined;
  private surges: { perHour: number; untilMs: number }[] = [];
  private moves = new Map<string, EngineMove>(); // engine moves, `with` lane only
  private overrides = new Map<string, OwnerOverride>(); // owner clicks, both lanes
  private holdUntil = new Map<string, number>(); // engine leaves these devices alone until then
  private meters: Record<Lane, LaneMeter> = { without: freshMeter(), with: freshMeter() };
  private decisions = new Map<string, { decision: Decision; explanation: string }>();
  private withReadings = new Map<string, HubDeviceReading>();
  private pendingApproval: string | null = null;
  private seq = { decision: 0, command: 0, chat: 0, run: 0 };

  // ---------- REST ----------

  async getCatalog(): Promise<EquipmentType[]> {
    await latency();
    return structuredClone(mockCatalog);
  }

  async createKitchen(config: KitchenConfig): Promise<{ kitchen_id: string }> {
    this.stopLoop();
    this.config = structuredClone(config);
    this.devices = [];
    for (const entry of config.equipment) {
      const type = mockCatalog.find((t) => t.type_id === entry.type_id);
      if (!type) throw new ApiError(422, `Unknown equipment type ${entry.type_id}`);
      for (let n = 1; n <= entry.count; n++) {
        this.devices.push({
          device_id: `${type.type_id}_${n}`,
          name: `${type.name} ${n}`,
          type,
          importance: entry.importance,
          limits: structuredClone(entry.limits),
          jobRemainingMin: 0,
          nextJobMs: 0,
        });
      }
    }
    this.resetRun();
    await latency(1_200); // stands in for the 21-day warm-up
    this.checkCapReachable();
    return { kitchen_id: "mock_kitchen" };
  }

  async getKitchen(): Promise<KitchenView> {
    await latency();
    const config = this.requireKitchen();
    return { config: structuredClone(config), devices: this.devices.map((d) => this.toDevice(d)) };
  }

  async setImportance(deviceId: string, body: ImportanceUpdate): Promise<Device> {
    await latency();
    const d = this.requireDevice(deviceId);
    if (body.importance === "flexible" && d.type.category === "refrigeration" && limit(body.limits, "min_power_pct", 50) < 50) {
      throw new ApiError(422, "Refrigeration can't go below 50% power (food safety).");
    }
    d.importance = body.importance;
    d.limits = structuredClone(body.limits);
    this.moves.delete(deviceId);
    this.checkCapReachable();
    return this.toDevice(d);
  }

  async setPeakCap(peakCapKw: number): Promise<Meter> {
    await latency();
    const config = this.requireKitchen();
    config.peak_cap_kw = peakCapKw;
    this.checkCapReachable();
    return this.meterView("with");
  }

  async simControl(body: SimControlRequest): Promise<ClockState> {
    await latency();
    this.requireKitchen();
    if (body.speed) this.speed = body.speed;
    if (body.action === "reset") {
      this.resetRun();
    } else if (body.action === "pause") {
      this.playing = false;
      this.stopLoop();
    } else if (!this.pendingApproval) {
      this.playing = true;
      this.startLoop();
    }
    if (body.speed && this.playing) this.startLoop();
    this.emitClock();
    return this.clockState();
  }

  async deviceCommand(deviceId: string, body: DeviceCommandRequest): Promise<Command> {
    await latency();
    const d = this.requireDevice(deviceId);
    switch (body.action) {
      case "off":
        this.overrides.set(deviceId, { kind: "off" });
        break;
      case "reduce":
        this.overrides.set(deviceId, { kind: "reduce", pct: body.value ?? 50 });
        break;
      case "delay":
        this.overrides.set(deviceId, { kind: "delay", untilMs: this.simMs + (body.value ?? 15) * MIN_MS });
        break;
      case "start":
        this.overrides.delete(deviceId);
        if (d.type.power_model === "job") d.jobRemainingMin = cycleMin(d.type);
        break;
      case "on":
      case "restore":
        this.overrides.delete(deviceId);
        break;
    }
    // The owner always wins: drop any engine move and keep the engine off this device for a while.
    this.moves.delete(deviceId);
    this.holdUntil.set(deviceId, this.simMs + OWNER_HOLD_MIN * MIN_MS);
    return {
      command_id: `c_${String(++this.seq.command).padStart(4, "0")}`,
      ts: iso(this.simMs),
      device_id: deviceId,
      action: body.action,
      value: body.value ?? null,
      decision_id: null,
      issued_by: "owner",
    };
  }

  async addCustomers(body: CustomerEventRequest): Promise<void> {
    await latency();
    this.surges.push({ perHour: (body.customers * 60) / body.duration_min, untilMs: this.simMs + body.duration_min * MIN_MS });
  }

  async approve(decisionId: string, approve: boolean): Promise<Decision> {
    await latency();
    const entry = this.decisions.get(decisionId);
    if (!entry) throw new ApiError(404, `Unknown decision ${decisionId}`);
    if (entry.decision.status !== "awaiting_approval") throw new ApiError(409, `Decision ${decisionId} isn't waiting for approval.`);
    entry.decision = { ...entry.decision, status: approve ? "approved" : "declined" };
    if (approve && entry.decision.value != null) {
      this.moves.set(entry.decision.device_id, {
        kind: "reduce",
        pct: entry.decision.value,
        untilMs: this.simMs + ENGINE_REDUCE_MIN * MIN_MS,
      });
    }
    this.emitDecision(entry.decision, entry.explanation, "template");
    if (this.pendingApproval === decisionId) {
      this.pendingApproval = null;
      this.pausedReason = null;
      this.playing = true;
      this.startLoop();
      this.emitClock();
    }
    return entry.decision;
  }

  async undo(decisionId: string): Promise<Decision> {
    await latency();
    const entry = this.decisions.get(decisionId);
    if (!entry) throw new ApiError(404, `Unknown decision ${decisionId}`);
    if (entry.decision.status !== "executed" && entry.decision.status !== "approved") {
      throw new ApiError(409, `Decision ${decisionId} can't be undone (${entry.decision.status}).`);
    }
    entry.decision = { ...entry.decision, status: "undone" };
    this.moves.delete(entry.decision.device_id);
    this.holdUntil.set(entry.decision.device_id, this.simMs + OWNER_HOLD_MIN * MIN_MS);
    this.emitDecision(entry.decision, entry.explanation, "template");
    return entry.decision;
  }

  async listDecisions(limit = 50): Promise<Decision[]> {
    await latency();
    return [...this.decisions.values()].map((e) => e.decision).reverse().slice(0, limit);
  }

  async runBacktest(): Promise<{ run_id: string }> {
    await latency();
    const run_id = `run_${++this.seq.run}`;
    MOCK_MONTHS.forEach((month, i) => {
      setTimeout(() => this.emit({ type: "backtest_progress", run_id, month, pct: Math.round(((i + 1) / MOCK_MONTHS.length) * 100) }), 250 * (i + 1));
    });
    return { run_id };
  }

  async getBacktest(): Promise<BacktestResult[]> {
    await latency();
    return MOCK_MONTHS.map(mockBacktestMonth);
  }

  async chat(message: string): Promise<{ chat_id: string }> {
    const chat_id = `chat_${++this.seq.chat}`;
    const reply =
      `Mock assistant here. You asked: "${message.slice(0, 80)}". ` +
      "The real assistant answers with numbers from the engine's tools; this one only proves that streaming works.";
    const words = reply.split(" ");
    words.forEach((word, i) => {
      setTimeout(() => this.emit({ type: "chat_delta", chat_id, text: (i ? " " : "") + word }), 60 * (i + 1));
    });
    setTimeout(() => this.emit({ type: "chat_done", chat_id }), 60 * (words.length + 1));
    await latency();
    return { chat_id };
  }

  // ---------- /ws ----------

  subscribe(onMessage: (msg: WsMessage) => void, onStatus: (status: ConnectionStatus) => void): () => void {
    onStatus("connecting");
    const timer = setTimeout(() => {
      this.listeners.add(onMessage);
      onStatus("open");
      if (this.config) this.emitClock();
    }, 150);
    return () => {
      clearTimeout(timer);
      this.listeners.delete(onMessage);
    };
  }

  // ---------- run loop ----------

  private resetRun() {
    this.stopLoop();
    const config = this.requireKitchen();
    this.rng = mulberry32(config.seed);
    this.simMs = START_MS;
    this.playing = false;
    this.pausedReason = null;
    this.pendingApproval = null;
    this.surges = [];
    this.moves.clear();
    this.overrides.clear();
    this.holdUntil.clear();
    this.decisions.clear();
    this.meters = { without: freshMeter(), with: freshMeter() };
    for (const d of this.devices) {
      d.jobRemainingMin = 0;
      d.nextJobMs = START_MS + Math.floor(this.rng() * 40) * MIN_MS;
    }
    this.tick(false); // so the UI has a first reading before Play
    this.emitClock();
  }

  private startLoop() {
    this.stopLoop();
    this.timer = setInterval(() => this.tick(true), Math.max(100, MIN_MS / this.speed));
  }

  private stopLoop() {
    clearInterval(this.timer);
    this.timer = undefined;
  }

  /** One simulated minute for both lanes, like runtime/loop.py. */
  private tick(advance: boolean) {
    const config = this.config;
    if (!config) return;
    if (advance) this.simMs += MIN_MS;
    const minute = Math.round((this.simMs - START_MS) / MIN_MS);
    const ts = iso(this.simMs);
    const hour = localHour(this.simMs);
    const open = hour >= hhmm(config.operating_hours.open) && hour < hhmm(config.operating_hours.close);
    const customersPerHour = this.customersPerHour(hour, open);
    const busy = Math.min(1.8, customersPerHour / 70);

    const without: HubDeviceReading[] = [];
    const withLane: HubDeviceReading[] = [];
    for (const d of this.devices) {
      const natural = this.applyOverride(d, this.naturalReading(d, open, hour, busy));
      without.push(natural);
      withLane.push(this.applyMove(d, natural));
    }
    this.withReadings = new Map(withLane.map((r) => [r.device_id, r]));

    const replanTick = !advance || minute % REPLAN_EVERY_MIN === 0;
    const newDecisions: Decision[] = [];
    if (advance && replanTick) {
      const d = this.replan(ts, sumKw(withLane), config);
      if (d) newDecisions.push(d);
    }
    const approvalDue = minute >= FIRST_APPROVAL_AT_MIN && (minute - FIRST_APPROVAL_AT_MIN) % APPROVAL_EVERY_MIN === 0;
    if (advance && open && approvalDue && !this.pendingApproval) {
      const d = this.proposeOutsideRules(ts, sumKw(withLane));
      if (d) newDecisions.push(d);
    }

    for (const lane of ["without", "with"] as const) {
      const readings = lane === "without" ? without : withLane;
      const total = sumKw(readings);
      this.updateMeter(lane, total, advance);
      this.emit({
        type: "tick",
        data: {
          lane,
          ts,
          hub: { ts, total_kw: total, devices: readings, source: "simulated" },
          meter: this.meterView(lane),
          customers_per_hour: Math.round(customersPerHour),
          new_decisions: lane === "with" ? newDecisions : [],
          forecast_kw: lane === "with" && replanTick ? this.forecast(config) : null,
        },
      });
    }

    for (const d of newDecisions) {
      const { explanation } = this.decisions.get(d.decision_id)!;
      if (d.status === "awaiting_approval") {
        this.pendingApproval = d.decision_id;
        this.emit({ type: "approval_request", data: d, explanation, expires_at: iso(this.simMs + 10 * MIN_MS) });
        this.playing = false;
        this.pausedReason = "awaiting_approval";
        this.stopLoop();
        this.emitClock();
      } else {
        this.emitDecision(d, explanation, "template");
        if (d.effect.saving_usd >= 1) setTimeout(() => this.upgradeToAi(d.decision_id), AI_DELAY_MS);
      }
    }
  }

  private customersPerHour(hour: number, open: boolean): number {
    this.surges = this.surges.filter((s) => s.untilMs > this.simMs);
    if (!open) return 0;
    const surge = this.surges.reduce((s, x) => s + x.perHour, 0);
    return (profileCustomersPerHour(hour) + surge) * (0.9 + 0.2 * this.rng());
  }

  private naturalReading(d: MockDevice, open: boolean, hour: number, busy: number): HubDeviceReading {
    const rated = d.type.rated_kw;
    const r = (power_kw: number, state: DeviceState): HubDeviceReading => ({ device_id: d.device_id, power_kw: round2(power_kw), state });
    switch (d.type.power_model) {
      case "fixed":
        return open ? r(rated, "on") : r(0, "off");
      case "cycling":
        return r(this.rng() < 0.35 + 0.2 * busy ? rated : rated * 0.15, "on");
      case "thermal": {
        const sun = Math.max(0, Math.sin((Math.PI * (hour - 8)) / 14));
        return r(rated * (0.45 + 0.35 * sun + 0.05 * busy + 0.03 * (this.rng() - 0.5)), "on");
      }
      case "demand_driven":
        return open ? r(Math.min(rated, rated * (0.15 + 0.45 * busy) * (0.92 + 0.16 * this.rng())), "on") : r(0, "off");
      case "job": {
        if (d.jobRemainingMin <= 0 && open && this.simMs >= d.nextJobMs) {
          const idleMin = d.type.type_id === "dishwasher" ? 15 + 45 * (1 - Math.min(1, busy)) : 60;
          d.jobRemainingMin = cycleMin(d.type);
          d.nextJobMs = this.simMs + (cycleMin(d.type) + idleMin) * MIN_MS;
        }
        if (d.jobRemainingMin > 0) {
          d.jobRemainingMin -= 1;
          return r(rated, "running_job");
        }
        return r(0, "off");
      }
    }
  }

  private applyOverride(d: MockDevice, natural: HubDeviceReading): HubDeviceReading {
    const o = this.overrides.get(d.device_id);
    if (!o) return natural;
    if (o.kind === "off") return { ...natural, power_kw: 0, state: "off" };
    if (o.kind === "reduce") return { ...natural, power_kw: round2((natural.power_kw * o.pct) / 100), state: "reduced" };
    if (this.simMs >= o.untilMs) {
      this.overrides.delete(d.device_id);
      return natural;
    }
    return { ...natural, power_kw: 0, state: "waiting" };
  }

  private applyMove(d: MockDevice, natural: HubDeviceReading): HubDeviceReading {
    const m = this.moves.get(d.device_id);
    if (!m) return natural;
    switch (m.kind) {
      case "reduce":
        if (this.simMs >= m.untilMs) {
          this.moves.delete(d.device_id);
          return natural;
        }
        return { ...natural, power_kw: round2((natural.power_kw * m.pct) / 100), state: "reduced" };
      case "delay":
        if (this.simMs >= m.untilMs) {
          this.moves.set(d.device_id, { kind: "catch_up", remainingMin: m.owedMin });
          return this.applyMove(d, natural);
        }
        return { ...natural, power_kw: 0, state: "waiting" };
      case "catch_up":
        m.remainingMin -= 1;
        if (m.remainingMin <= 0) this.moves.delete(d.device_id);
        return { ...natural, power_kw: d.type.rated_kw, state: "running_job" };
    }
  }

  /** Every 5 sim minutes: if the `with` lane is near the cap, delay a running job, else turn down a flexible device. */
  private replan(ts: string, withTotalKw: number, config: KitchenConfig): Decision | null {
    if (withTotalKw <= config.peak_cap_kw * 0.95) return null;
    const free = (d: MockDevice) =>
      !this.moves.has(d.device_id) && !this.overrides.has(d.device_id) && (this.holdUntil.get(d.device_id) ?? 0) <= this.simMs;

    const job = this.devices.find(
      (d) => d.importance === "deferrable" && free(d) && this.withReadings.get(d.device_id)?.state === "running_job",
    );
    if (job) {
      const delayMin = Math.min(20, limit(job.limits, "max_delay_min", 60));
      this.moves.set(job.device_id, { kind: "delay", untilMs: this.simMs + delayMin * MIN_MS, owedMin: Math.max(1, job.jobRemainingMin) });
      return this.recordDecision(ts, job, "delay", delayMin, "avoid_new_peak", true, "executed", withTotalKw, job.type.rated_kw);
    }

    const flex = this.largestFlexible(free);
    if (flex) {
      const pct = Math.max(limit(flex.limits, "min_power_pct", 40), 60);
      const nowKw = this.withReadings.get(flex.device_id)?.power_kw ?? 0;
      const forMin = Math.min(ENGINE_REDUCE_MIN, limit(flex.limits, "max_reduce_min", 30));
      this.moves.set(flex.device_id, { kind: "reduce", pct, untilMs: this.simMs + forMin * MIN_MS });
      return this.recordDecision(ts, flex, "reduce", pct, "stay_under_cap", true, "executed", withTotalKw, (nowKw * (100 - pct)) / 100);
    }
    return null;
  }

  /** Every 30 sim minutes: a move below the owner's minimum, so the approval flow has something to show. */
  private proposeOutsideRules(ts: string, withTotalKw: number): Decision | null {
    const flex = this.largestFlexible((d) => !this.overrides.has(d.device_id));
    if (!flex) return null;
    const pct = Math.max(10, limit(flex.limits, "min_power_pct", 40) - 20);
    const nowKw = this.withReadings.get(flex.device_id)?.power_kw ?? 0;
    return this.recordDecision(ts, flex, "reduce", pct, "stay_under_cap", false, "awaiting_approval", withTotalKw, (nowKw * (100 - pct)) / 100);
  }

  private largestFlexible(ok: (d: MockDevice) => boolean): MockDevice | undefined {
    const power = (d: MockDevice) => this.withReadings.get(d.device_id)?.power_kw ?? 0;
    return this.devices.filter((d) => d.importance === "flexible" && ok(d)).sort((a, b) => power(b) - power(a))[0];
  }

  private recordDecision(
    ts: string,
    d: MockDevice,
    action: CommandAction,
    value: number,
    reason: ReasonCode,
    insideRules: boolean,
    status: DecisionStatus,
    beforeKw: number,
    savedKw: number,
  ): Decision {
    const before = round2(beforeKw);
    const after = round2(beforeKw - savedKw);
    const decision: Decision = {
      decision_id: `d_${String(++this.seq.decision).padStart(4, "0")}`,
      ts,
      device_id: d.device_id,
      action,
      value,
      reason_code: reason,
      inside_rules: insideRules,
      status,
      effect: {
        peak_before_kw: before,
        peak_after_kw: after,
        saving_usd: round2(DEMAND_USD_PER_KW * Math.max(0, before - Math.max(after, this.meters.with.monthPeakKw))),
      },
    };
    const kw = `(${before.toFixed(1)} → ${after.toFixed(1)} kW)`;
    const explanation =
      status === "awaiting_approval"
        ? `Turning ${d.name} down to ${value}% would keep you under the cap ${kw}, but that's below its ${limit(d.limits, "min_power_pct", 40)}% minimum.`
        : action === "delay"
          ? `Delayed ${d.name} ${value} min to avoid a new peak ${kw}.`
          : `Turned ${d.name} down to ${value}% to stay under the cap ${kw}.`;
    this.decisions.set(decision.decision_id, { decision, explanation });
    return decision;
  }

  private upgradeToAi(decisionId: string) {
    const entry = this.decisions.get(decisionId);
    if (!entry) return;
    const name = this.devices.find((d) => d.device_id === entry.decision.device_id)?.name ?? entry.decision.device_id;
    const { peak_before_kw, peak_after_kw } = entry.decision.effect;
    entry.explanation =
      `Mock AI: the kitchen was heading for a new monthly peak, so WattWise eased off ${name}. ` +
      `That keeps the 15-minute average near ${peak_after_kw.toFixed(1)} kW instead of ${peak_before_kw.toFixed(1)} kW.`;
    this.emitDecision(entry.decision, entry.explanation, "ai");
  }

  private forecast(config: KitchenConfig): number[] {
    return Array.from({ length: 8 }, (_, k) => {
      const hour = localHour(this.simMs + (k + 0.5) * BLOCK_MS);
      const open = hour >= hhmm(config.operating_hours.open) && hour < hhmm(config.operating_hours.close);
      const busy = open ? Math.min(1.8, profileCustomersPerHour(hour) / 70) : 0;
      const sun = Math.max(0, Math.sin((Math.PI * (hour - 8)) / 14));
      const kw = this.devices.reduce((s, d) => {
        const rated = d.type.rated_kw;
        switch (d.type.power_model) {
          case "fixed":
            return s + (open ? rated : 0);
          case "cycling":
            return s + rated * (0.15 + 0.85 * (0.35 + 0.2 * busy));
          case "thermal":
            return s + rated * (0.45 + 0.35 * sun + 0.05 * busy);
          case "demand_driven":
            return s + (open ? rated * (0.15 + 0.45 * busy) : 0);
          case "job":
            return s + (open ? rated * 0.4 : 0);
        }
      }, 0);
      return Math.round(kw * 10) / 10;
    });
  }

  private updateMeter(lane: Lane, totalKw: number, advance: boolean) {
    const m = this.meters[lane];
    m.totalKw = totalKw;
    if (advance) m.energyKwhToday += totalKw / 60;
    const blockStart = Math.floor(this.simMs / BLOCK_MS) * BLOCK_MS;
    if (blockStart !== m.blockStartMs) {
      if (m.blockCount) m.monthPeakKw = Math.max(m.monthPeakKw, m.blockSumKw / m.blockCount);
      m.blockStartMs = blockStart;
      m.blockSumKw = 0;
      m.blockCount = 0;
    }
    m.blockSumKw += totalKw;
    m.blockCount += 1;
  }

  private meterView(lane: Lane): Meter {
    const m = this.meters[lane];
    const costToday = m.energyKwhToday * ENERGY_USD_PER_KWH;
    return {
      ts: iso(this.simMs),
      total_kw: m.totalKw,
      block_avg_kw: round2(m.blockCount ? m.blockSumKw / m.blockCount : m.totalKw),
      block_start: iso(m.blockStartMs),
      month_peak_kw: round2(m.monthPeakKw),
      peak_cap_kw: this.config?.peak_cap_kw ?? 0,
      energy_kwh_today: round2(m.energyKwhToday),
      cost_usd_today: round2(costToday),
      cost_usd_month: round2(MONTH_ENERGY_USD_BEFORE_TODAY + costToday + m.monthPeakKw * DEMAND_USD_PER_KW),
    };
  }

  private checkCapReachable() {
    const config = this.config;
    if (!config) return;
    const unavoidableKw = this.devices.reduce((s, d) => {
      if (d.importance === "always_on") return s + d.type.rated_kw * 0.6;
      if (d.importance === "flexible") return s + (d.type.rated_kw * limit(d.limits, "min_power_pct", 40)) / 100;
      return s;
    }, 0);
    if (unavoidableKw > config.peak_cap_kw) {
      this.emit({
        type: "warning",
        code: "cap_unreachable",
        message: `Your always-on equipment alone needs ${unavoidableKw.toFixed(1)} kW. Raise the cap or change an importance.`,
        data: { unavoidable_kw: round2(unavoidableKw) },
      });
    }
  }

  // ---------- helpers ----------

  private toDevice(d: MockDevice): Device {
    const r = this.withReadings.get(d.device_id);
    return {
      device_id: d.device_id,
      type_id: d.type.type_id,
      name: d.name,
      importance: d.importance,
      state: r?.state ?? "off",
      power_kw: r?.power_kw ?? 0,
      rated_kw: d.type.rated_kw,
      source: "simulated",
    };
  }

  private requireKitchen(): KitchenConfig {
    if (!this.config) throw new ApiError(404, "No kitchen yet. Build one first.");
    return this.config;
  }

  private requireDevice(deviceId: string): MockDevice {
    this.requireKitchen();
    const d = this.devices.find((x) => x.device_id === deviceId);
    if (!d) throw new ApiError(404, `Unknown device ${deviceId}`);
    return d;
  }

  private clockState(): ClockState {
    return { playing: this.playing, speed: this.speed, sim_ts: iso(this.simMs), paused_reason: this.pausedReason };
  }

  private emitClock() {
    this.emit({ type: "clock", ...this.clockState() });
  }

  private emitDecision(decision: Decision, explanation: string, source: "ai" | "template") {
    this.emit({ type: "decision", data: decision, explanation, explanation_source: source });
  }

  private emit(msg: WsMessage) {
    for (const listener of this.listeners) listener(structuredClone(msg));
  }
}

// ---------- backtest ----------

const MOCK_MONTHS = Array.from({ length: 12 }, (_, i) => `2025-${String(i + 1).padStart(2, "0")}`);

function mockBill(period: string, energyKwh: number, peakKw: number): Bill {
  const energyCost = round2(energyKwh * 0.19);
  const demandCost = round2(peakKw * DEMAND_USD_PER_KW);
  return {
    period,
    energy_kwh: round2(energyKwh),
    energy_cost_usd: energyCost,
    demand_charges: [{ name: "max_demand", peak_kw: round2(peakKw), cost_usd: demandCost }],
    total_usd: round2(energyCost + demandCost),
    tariff_id: "mock-tariff",
  };
}

function mockBacktestMonth(month: string, i: number): BacktestResult {
  const season = 1 + 0.25 * Math.sin((Math.PI * (i - 3)) / 6); // summer-heavy
  const energyKwh = 21_000 * season;
  const peakWithout = 44 * season;
  return {
    dataset: "MOCK DATA, not a real dataset",
    month,
    policies: {
      without: mockBill(month, energyKwh, peakWithout),
      timer: mockBill(month, energyKwh, peakWithout - 2.5),
      with: mockBill(month, energyKwh, peakWithout - 6.5),
    },
    checks: { baseline_matches_raw: true, energy_conserved: true, rule_violations: 0 },
    assumptions_id: "base",
  };
}

// Pure so a real (non-mock) build drops the whole mock.
export const mockTransport: Transport = /* @__PURE__ */ new MockServer();
