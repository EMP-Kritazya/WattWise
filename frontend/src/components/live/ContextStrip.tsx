import { CalendarDays, Thermometer, Users, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { useLiveContext } from "@/data";
import { fmtSimTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataLabel } from "@/types";

const STRESS: Record<string, string> = {
  low: "text-lane-with",
  normal: "text-muted-foreground",
  high: "text-lane-without",
};

/**
 * What the Fetch agents see outside the kitchen (UI.md "Context strip"): outdoor temperature, electricity price and
 * grid stress, nearby events and the crowd effect. Numbers are shown exactly as the agents posted them, each with its
 * source label (live_api / recorded).
 */
export function ContextStrip() {
  const ctx = useLiveContext();
  if (!ctx) return null;
  const temps = ctx.weather?.hourly ?? [];
  const prices = ctx.prices?.hourly ?? [];
  const event = ctx.events?.items[0];

  return (
    <div className="grid gap-3 rounded-xl border bg-card px-4 py-3 sm:grid-cols-2 xl:grid-cols-4">
      {ctx.weather && (
        <Cell icon={<Thermometer className="size-4" />} title="Outdoor" label={ctx.weather.label} source={ctx.weather.source}>
          <span className="text-lg font-semibold tabular-nums">{temps[0] ? `${temps[0].temp_c.toFixed(1)} °C` : "–"}</span>
          <span className="ml-2 text-xs text-muted-foreground tabular-nums">
            next: {temps.slice(1, 5).map((t) => `${Math.round(t.temp_c)}°`).join(" · ")}
          </span>
        </Cell>
      )}
      {ctx.prices && (
        <Cell icon={<Zap className="size-4" />} title="Electricity price" label={ctx.prices.label} source={ctx.prices.source}>
          <span className="text-lg font-semibold tabular-nums">{prices[0] ? `$${prices[0].usd_per_kwh.toFixed(2)}/kWh` : "–"}</span>
          <Sparkline values={prices.map((p) => p.usd_per_kwh)} />
          <span className={cn("ml-2 text-xs font-medium", STRESS[ctx.prices.stress])}>grid stress {ctx.prices.stress}</span>
        </Cell>
      )}
      {ctx.events && (
        <Cell icon={<CalendarDays className="size-4" />} title="Nearby" label={ctx.events.label} source={ctx.events.source}>
          {event ? (
            <span className="text-sm">
              <b>{event.name}</b>
              <span className="text-muted-foreground">
                {" "}
                · {event.distance_km.toFixed(1)} km · {fmtSimTime(event.start)}
              </span>
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">No events nearby</span>
          )}
        </Cell>
      )}
      {ctx.crowd_effect && (
        <Cell icon={<Users className="size-4" />} title="Crowd effect" label={null} source={`set by ${ctx.crowd_effect.set_by}`}>
          <span className="text-lg font-semibold capitalize">{ctx.crowd_effect.value}</span>
          <span className="ml-2 text-xs text-muted-foreground">{ctx.crowd_effect.reason}</span>
        </Cell>
      )}
    </div>
  );
}

function Cell({ icon, title, label, source, children }: { icon: ReactNode; title: string; label: DataLabel | null; source: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        {title}
        {label && <span className="rounded bg-secondary px-1 text-[10px] uppercase">{label === "live_api" ? "live" : "recorded"}</span>}
      </div>
      <div className="mt-0.5 flex flex-wrap items-baseline">{children}</div>
      <div className="truncate text-[10px] text-muted-foreground/70">{source}</div>
    </div>
  );
}

/** A tiny line of the posted values (shape only; no numbers are derived from it). */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 60},${16 - ((v - lo) / span) * 14 - 1}`).join(" ");
  return (
    <svg viewBox="0 0 60 16" className="ml-2 h-4 w-14 self-center" aria-hidden>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-importance-deferrable" />
    </svg>
  );
}
