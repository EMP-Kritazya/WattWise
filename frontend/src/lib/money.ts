import { useDashboardStore as useSim } from "@/data";

/** What a money figure shows while the kitchen's tariff is not a real one. */
export const NO_REAL_TARIFF = "Needs a real tariff";
export const NO_REAL_TARIFF_HINT =
  "Dollar amounts appear once the engine bills on a real utility tariff. The current tariff is illustrative, so no $ figure is shown.";

/**
 * True only when the kitchen's tariff is a real one (`Tariff.label` "urdb"). The engine computes every $ on the tariff it is
 * given; on the `illustrative` demo tariff those numbers are not real money, so the UI hides them (Ashirwad, Oct 25).
 */
export function useRealTariff(): boolean {
  return useSim((s) => s.kitchen?.tariff?.label === "urdb");
}
