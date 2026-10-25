import { useMemo, useState } from "react";
import { ArrowDown, CircleHelp, Clock, Power, Zap } from "lucide-react";
import { useDeviceMeta } from "@/hooks/useDeviceMeta";
import { fmtAction, fmtKw, fmtSimTime } from "@/lib/format";
import { IMPORTANCE_LABEL, STATUS_LABEL } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";
import type { HubDeviceReading, Lane } from "@/types";
import { DeviceDetails } from "./DeviceDetails";

/** Presentation only: status and values are taken directly from the current hub report. */
export function ReadingStatus({ reading }: { reading?: HubDeviceReading }) {
  const state = reading?.state;
  const Icon = state === "waiting" ? Clock : state === "reduced" ? ArrowDown : state === "off" ? Power : state ? Zap : CircleHelp;
  const text = !state
    ? "No reading"
    : state === "on"
      ? "On"
      : state === "running_job"
        ? "Running job"
        : state === "waiting"
          ? "Waiting"
          : state === "reduced"
            ? "Reduced"
            : "Off";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium",
        state === "reduced"
          ? "text-blue-300"
          : state === "waiting"
            ? "text-amber-300"
            : state === "off" || !state
              ? "text-slate-400"
              : "text-emerald-300",
      )}
    >
      <Icon className="size-3.5" />
      {text}
    </span>
  );
}

export function DemandSummary() {
  const latest = useSim((s) => s.latest);
  const connection = useSim((s) => s.connection);
  const clock = useSim((s) => s.clock);
  return (
    <div className="border-b border-white/10 bg-slate-950/50 px-4 py-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
        <span>15-minute demand · the monthly maximum drives demand charges</span>
        <span role="status">
          {connection !== "open"
            ? "Connection lost · showing last received readings"
            : !latest.with
              ? "Waiting for hub readings"
              : clock?.paused_reason === "escalation"
                ? "Paused · your decision needed"
                : clock?.playing
                  ? "Simulation running"
                  : "Simulation paused"}{" "}
          · {transport.kind === "mock" ? "Mock data" : "Simulated"}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {(["without", "with"] as const).map((lane) => {
          const meter = latest[lane]?.meter;
          return (
            <div key={lane} className="min-w-0 border-l-2 pl-3" style={{ borderColor: lane === "with" ? "#34d399" : "#f87171" }}>
              <div className="text-xs text-slate-300">{lane === "with" ? "With WattWise" : "Without WattWise"}</div>
              <div className="mt-1 text-xl font-semibold tabular-nums sm:text-2xl">{fmtKw(meter?.block_avg_kw)}</div>
              <div className={cn("text-xs", meter && meter.block_avg_kw > meter.target_kw ? "text-red-300" : "text-slate-400")}>
                {!meter ? "Waiting for data" : meter.block_avg_kw > meter.target_kw ? "Above target" : "Within target"}
              </div>
            </div>
          );
        })}
        <div className="border-l border-white/15 pl-3">
          <div className="text-xs text-slate-300">Owner’s peak cap</div>
          <div className="mt-1 text-xl font-semibold tabular-nums sm:text-2xl">{fmtKw(latest.with?.meter.target_kw)}</div>
          <div className="text-xs text-slate-400">Target for both lanes</div>
        </div>
      </div>
    </div>
  );
}

/** Stable HTML companion to the scene: all equipment, including lighting, is keyboard-accessible. */
export function OperationsPanel({
  mode,
  selected,
  onSelect,
}: {
  mode: Lane | "compare";
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const metas = useDeviceMeta();
  const latest = useSim((s) => s.latest);
  const connection = useSim((s) => s.connection);
  const feed = useSim((s) => s.feed);
  const [filter, setFilter] = useState<"all" | "active" | "changed">("all");
  const lane = mode === "without" ? "without" : "with";
  const readings = useMemo(() => new Map(latest[lane]?.hub.devices.map((r) => [r.device_id, r])), [latest, lane]);
  const baseline = useMemo(() => new Map(latest.without?.hub.devices.map((r) => [r.device_id, r])), [latest.without]);
  const chosen = metas.find((m) => m.device.device_id === selected);
  const decisions = useMemo(
    () =>
      Object.values(feed).sort(
        (a, b) => b.decision.ts.localeCompare(a.decision.ts) || b.decision.decision_id.localeCompare(a.decision.decision_id),
      ),
    [feed],
  );
  const event = selected ? decisions.find((i) => i.decision.device_id === selected) : decisions[0];
  const visible = metas.filter((m) => {
    const r = readings.get(m.device.device_id);
    return filter === "all" || (filter === "active" ? r != null && r.power_kw > 0 : r?.state === "reduced" || r?.state === "waiting");
  });
  return (
    <aside className="flex min-h-0 flex-col border-t border-white/10 bg-[#111827] lg:border-t-0 lg:border-l" aria-label="Appliance status">
      <div className="border-b border-white/10 p-4">
        <h3 className="font-semibold">What is running?</h3>
        <p className="mt-1 text-xs text-slate-400">
          {mode === "compare"
            ? "Compare each appliance in the same simulation."
            : `${lane === "with" ? "With" : "Without"} WattWise · select an appliance to locate it.`}
        </p>
        <div className="mt-3 flex flex-wrap gap-1" aria-label="Filter appliances">
          {(
            [
              ["all", "All appliances"],
              ["active", "Drawing power"],
              ["changed", "Reduced / waiting"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
              className={cn(
                "rounded-md px-2 py-2 text-xs focus-visible:outline-2 focus-visible:outline-blue-300",
                filter === id ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="max-h-80 min-h-0 flex-1 overflow-y-auto lg:max-h-none">
        {mode === "compare" && (
          <div className="grid grid-cols-[1fr_80px_80px] gap-1 px-4 pt-3 text-right text-xs text-slate-400">
            <span />
            <span>Without</span>
            <span>With</span>
          </div>
        )}
        {visible.map((m) => {
          const id = m.device.device_id;
          const r = readings.get(id);
          const Icon = m.icon;
          return (
            <button
              type="button"
              key={id}
              aria-pressed={selected === id}
              onClick={() => onSelect(selected === id ? null : id)}
              className={cn(
                "flex w-full items-center gap-3 border-b border-white/5 px-4 py-3 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-300",
                selected === id ? "bg-blue-400/15" : "hover:bg-white/5",
              )}
            >
              <Icon className="size-4 shrink-0 text-slate-400" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{m.device.name}</span>
                <span className="text-xs text-slate-400">{IMPORTANCE_LABEL[m.device.importance]}</span>
              </span>
              {mode === "compare" && (
                <span className="w-20 shrink-0 text-right">
                  <span className="block text-sm tabular-nums">{fmtKw(baseline.get(id)?.power_kw)}</span>
                  <ReadingStatus reading={baseline.get(id)} />
                </span>
              )}
              <span className="w-20 shrink-0 text-right">
                <span className="block text-sm font-semibold tabular-nums">{fmtKw(r?.power_kw)}</span>
                <ReadingStatus reading={r} />
              </span>
            </button>
          );
        })}
        {!visible.length && <p className="p-4 text-sm text-slate-400">No appliances match this filter.</p>}
      </div>
      <div className="max-h-72 shrink-0 overflow-y-auto border-t border-white/10 p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
          {selected ? "Last WattWise decision for this appliance" : "Latest WattWise decision"}
        </div>
        {event ? (
          <div className="mt-2 text-sm">
            <div className="font-medium">
              {metas.find((m) => m.device.device_id === event.decision.device_id)?.device.name ?? event.decision.device_id} ·{" "}
              {fmtAction(event.decision.action, event.decision.value)}
            </div>
            <div className="mt-1 text-xs text-slate-400">
              {fmtSimTime(event.decision.ts)} · {STATUS_LABEL[event.decision.status]}
            </div>
            {event.explanation && <p className="mt-2 text-xs leading-relaxed text-slate-300">{event.explanation}</p>}
            <button type="button" onClick={() => onSelect(event.decision.device_id)} className="mt-2 rounded border border-blue-300/30 px-2 py-1.5 text-xs text-blue-300 hover:bg-blue-400/10">Locate appliance on floor</button>
            <p className="mt-2 text-xs text-slate-400">
              Engine’s projected peak: {fmtKw(event.decision.effect.peak_before_kw)} → {fmtKw(event.decision.effect.peak_after_kw)}
            </p>
          </div>
        ) : (
          <p className="mt-2 text-sm text-slate-400">No decision yet. Add customers to demonstrate how WattWise responds.</p>
        )}
        {chosen && (
          <details key={`${lane}:${selected}`} className="mt-3">
            <summary className="cursor-pointer py-2 text-sm text-blue-300">Appliance details & owner controls</summary>
            {mode === "with" && readings.has(chosen.device.device_id) && connection === "open" ? (
              <DeviceDetails meta={chosen} reading={readings.get(chosen.device.device_id)} onClose={() => onSelect(null)} />
            ) : (
              <p className="text-xs text-slate-400">
                Owner controls are available in the With WattWise view when connected and readings are available.
              </p>
            )}
          </details>
        )}
      </div>
    </aside>
  );
}
