import type { CommandAction } from "@/types";

// Formatting only: every number on screen comes from the server; the UI never computes them (UI.md).
// kW with 1 decimal, $ with 2 decimals, sim time shown in the restaurant's time zone.
const LA = "America/Los_Angeles";
const clockFmt = new Intl.DateTimeFormat("en-US", { timeZone: LA, weekday: "short", hour: "numeric", minute: "2-digit" });
const timeFmt = new Intl.DateTimeFormat("en-US", { timeZone: LA, hour: "numeric", minute: "2-digit" });
const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtKw = (kw: number | null | undefined) => (kw == null ? "–" : `${kw.toFixed(1)} kW`);
export const fmtUsd = (usd: number | null | undefined) => (usd == null ? "–" : usdFmt.format(usd));
export const fmtSimClock = (ts: string | number) => clockFmt.format(new Date(ts));
export const fmtSimTime = (ts: string | number) => timeFmt.format(new Date(ts));

export function fmtAction(action: CommandAction, value: number | null): string {
  switch (action) {
    case "delay":
      return `Delay ${value ?? "?"} min`;
    case "reduce":
      return `Turn down to ${value ?? "?"}%`;
    case "start":
      return "Start job";
    case "restore":
      return "Restore";
    case "on":
      return "Turn on";
    case "off":
      return "Turn off";
  }
}
