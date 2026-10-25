import type { Command, CommandAck, Lane } from "@/types";
import { clamp, round } from "@/sim/math";
import type { ApplianceInputs } from "@/sim/types";
import { BaseAppliance } from "./base";

export class JobAppliance extends BaseAppliance {
  private delayRemainingMin = 0;
  private jobRemainingMin = 0;
  private dirtyRacks = 0;
  private iceLevelPct = 72;

  apply(command: Command, lane: Lane): CommandAck {
    if (command.action === "delay") {
      const base: CommandAck = { command_id: command.command_id, lane, ok: true, applied_value: command.value, reason: null };
      if (this.jobRemainingMin > 0) return { ...base, ok: false, applied_value: null, reason: "job_running" };
      const maximum = "max_delay_min" in this.definition.limits ? this.definition.limits.max_delay_min : 0;
      const requested = command.value ?? 0;
      const applied = clamp(requested, 0, maximum);
      this.delayRemainingMin = applied;
      this.state = applied > 0 ? "waiting" : "off";
      return { ...base, applied_value: applied, reason: applied === requested ? null : "out_of_range" };
    }
    if (command.action === "start") {
      if (this.jobRemainingMin <= 0) this.jobRemainingMin = this.cycleMinutes();
      this.delayRemainingMin = 0;
      this.enabled = true;
      return { command_id: command.command_id, lane, ok: true, applied_value: null, reason: null };
    }
    return super.apply(command, lane);
  }

  step(minutes: number, inputs: ApplianceInputs) {
    if (this.typeId === "dishwasher") this.dirtyRacks += inputs.arrivals * 0.15;
    if (this.typeId === "ice_machine") this.iceLevelPct -= inputs.arrivals * 0.28;

    this.delayRemainingMin = Math.max(0, this.delayRemainingMin - minutes);
    const workReady = this.typeId === "dishwasher" ? this.dirtyRacks >= 12 : this.iceLevelPct <= 28;
    if (this.enabled && inputs.is_open && this.jobRemainingMin <= 0 && this.delayRemainingMin <= 0 && workReady) {
      this.jobRemainingMin = this.cycleMinutes();
    }

    if (this.enabled && this.jobRemainingMin > 0) {
      this.powerKw = this.ratedKw;
      this.state = "running_job";
      this.jobRemainingMin = Math.max(0, this.jobRemainingMin - minutes);
      if (this.jobRemainingMin === 0) {
        if (this.typeId === "dishwasher") this.dirtyRacks = Math.max(0, this.dirtyRacks - 12);
        if (this.typeId === "ice_machine") this.iceLevelPct = Math.min(100, this.iceLevelPct + 70);
      }
    } else {
      this.powerKw = 0;
      this.state = this.delayRemainingMin > 0 ? "waiting" : "off";
    }

    this.iceLevelPct = clamp(this.iceLevelPct, 0, 100);
    this.physical = this.typeId === "dishwasher"
      ? { dirty_racks: Math.round(this.dirtyRacks), job_remaining_min: round(this.jobRemainingMin) }
      : { ice_level_pct: Math.round(this.iceLevelPct), job_remaining_min: round(this.jobRemainingMin) };
  }

  private cycleMinutes() {
    return (this.definition.equipment.params as { cycle_min: number }).cycle_min;
  }
}
