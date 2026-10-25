// The only door screens use for live data (UI.md): hooks over the store, which is fed by SpacetimeDB, /ws or the mock.
// Swapping the live source never touches a screen.
import { useMemo } from "react";
import { useSim } from "@/store/sim";
import type { Escalation, Lane, Proposal } from "@/types";

export { requestSurge, startLive } from "./live";
export { api, useApi } from "./useApi";
export { publishHostDevices, useDevices } from "./useDevices";
export { isFixtureHub, useHubHost, type HubConnectionState } from "./useHubHost";
export { useLive } from "./useLive";
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
