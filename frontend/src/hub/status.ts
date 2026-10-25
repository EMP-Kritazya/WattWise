import { create } from "zustand";
import type { ClockState, HubReportMessage } from "@/types";

export type HubConnectionState = "connecting" | "connected" | "host_taken" | "offline" | "error";

interface HubStatusState {
  connection: HubConnectionState;
  message: string;
  tickId: number;
  simTs: string | null;
  playing: boolean;
  speed: number;
  pausedReason: ClockState["paused_reason"];
  lastReport: HubReportMessage | null;
}

export const useHubStatus = create<HubStatusState>(() => ({
  connection: "offline",
  message: "Simulation host is offline",
  tickId: 0,
  simTs: null,
  playing: false,
  speed: 1,
  pausedReason: "sim_host_offline",
  lastReport: null,
}));
