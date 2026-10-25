// The only door screens use for live data (UI.md): hooks over the store, which is fed by SpacetimeDB, /ws or the mock.
// Swapping the live source never touches a screen.
import { useMemo } from "react";
import { useSim } from "@/store/sim";
import type { BacktestMonthRow, BacktestPointRow, Escalation, Lane, Proposal } from "@/types";
import { useLive } from "./useLive";

export { requestSurge, startLive } from "./live";
export { api, useApi } from "./useApi";
export { publishHostDevices, useDevices } from "./useDevices";
export { isFixtureHub, useHubHost, type HubConnectionState } from "./useHubHost";
export { useLive } from "./useLive";
export { backtestMonthOf, backtestPointOf } from "./rows";
export type { BlockPoint, ChatMessage, FeedItem, LanePoint, LiveSourceKind, Warning } from "@/store/sim";

/** Legacy screen store, retained only while C2 migrates the existing screens to typed live rows. */
export const useDashboardStore = useSim;

export const useLaneTick = (lane: Lane) => useSim((s) => s.latest[lane]);
export const useClock = () => useSim((s) => s.clock);
export const useComparison = () => useSim((s) => s.comparison);
export const useLiveContext = () => useSim((s) => s.context);
export const useAgentLog = () => useSim((s) => s.agentLog);
export const useLiveSource = () => useSim((s) => s.liveSource);

/** Escalations newest first. */
export function useEscalations(): Escalation[] {
  const all = useSim((s) => s.escalations);
  return useMemo(() => Object.values(all).sort((a, b) => b.ts.localeCompare(a.ts)), [all]);
}

/** Proposals waiting for the owner's Confirm / Cancel, newest first. */
export function usePendingProposals(): Proposal[] {
  const all = useSim((s) => s.proposals);
  return useMemo(() => Object.values(all).filter((p) => p.status === "pending").sort((a, b) => b.ts.localeCompare(a.ts)), [all]);
}

/** The latest backtest run's rows (SpacetimeDB `backtest_point` / `backtest_month`, or the same rows built from /ws
 * `backtest_point` / `backtest_month` messages, or the fixture tables in mock mode). */
export interface BacktestRows {
  /** run id of the rows shown (the newest run; null before any row arrives). */
  runId: string | null;
  /** one per replayed local day, oldest first (`day` ascending): the Proof chart's running line. */
  points: BacktestPointRow[];
  /** one per finished month, oldest first (`month` ascending): the month marks. */
  months: BacktestMonthRow[];
}

/**
 * Proof screen hook. Rows are engine numbers as published (the screen never subtracts or multiplies);
 * `backtestPointOf(row)` / `backtestMonthOf(row)` parse the JSON columns into BacktestPoint / BacktestResult.
 */
export function useBacktestRows(): BacktestRows {
  const points = useLive((s) => s.backtest_point);
  const months = useLive((s) => s.backtest_month);
  return useMemo(() => {
    const all = [...points.map((r) => r.run_id), ...months.map((r) => r.run_id)].sort();
    const runId = all.length ? all[all.length - 1] : null;
    return {
      runId,
      points: points.filter((r) => r.run_id === runId).sort((a, b) => a.day.localeCompare(b.day)),
      months: months.filter((r) => r.run_id === runId).sort((a, b) => a.month.localeCompare(b.month)),
    };
  }, [points, months]);
}
export { useEvalArtifact } from "./useEvalArtifact";
