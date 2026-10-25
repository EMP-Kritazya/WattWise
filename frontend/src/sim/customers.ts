import type { SimInputs, Surge } from "@/types";
import { clamp, round } from "@/sim/math";
import { SeededRandom } from "@/sim/rng";
import type { CustomerSnapshot } from "@/sim/types";

interface ActiveSurge extends Surge { remainingMin: number }

/** One customer generator is shared by both lanes so policy is the only difference between them. */
export class CustomerFlow {
  private readonly random: SeededRandom;
  private readonly activeSurges = new Map<string, ActiveSurge>();
  private readonly minuteHistory: number[] = [];
  private ordersInProgress = 0;

  constructor(seed: number) {
    this.random = new SeededRandom(seed);
  }

  step(minutes: number, inputs: SimInputs, surges: Surge[]): CustomerSnapshot {
    for (const surge of surges) {
      if (!this.activeSurges.has(surge.surge_id)) {
        this.activeSurges.set(surge.surge_id, { ...surge, remainingMin: surge.duration_min });
      }
    }

    let arrivals = 0;
    for (let minute = 0; minute < minutes; minute += 1) {
      const basePerHour = inputs.is_open ? 72 * (inputs.crowd_multiplier ?? 1) : 0;
      const surgePerHour = [...this.activeSurges.values()].reduce(
        (sum, surge) => sum + (surge.customers / surge.duration_min) * 60,
        0,
      );
      const thisMinute = this.random.poisson((basePerHour + surgePerHour) / 60);
      arrivals += thisMinute;
      this.minuteHistory.push(thisMinute);
      if (this.minuteHistory.length > 60) this.minuteHistory.shift();

      for (const [id, surge] of this.activeSurges) {
        surge.remainingMin -= 1;
        if (surge.remainingMin <= 0) this.activeSurges.delete(id);
      }
    }

    const completionRate = clamp(minutes / 12, 0, 1);
    this.ordersInProgress = Math.max(0, this.ordersInProgress * (1 - completionRate) + arrivals);
    return {
      arrivals,
      customersPerHour: this.minuteHistory.reduce((sum, value) => sum + value, 0),
      ordersInProgress: round(this.ordersInProgress, 2),
    };
  }
}
