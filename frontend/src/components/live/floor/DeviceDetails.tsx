import { Play, Power, RotateCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAction } from "@/hooks/useAction";
import type { DeviceMeta } from "@/hooks/useDeviceMeta";
import { fmtKw } from "@/lib/format";
import { DEVICE_STATE_LABEL, IMPORTANCE_LABEL } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useLive as useSim } from "@/data";
import { transport } from "@/transport";
import type { HubDeviceReading, Importance, ImportanceLimits } from "@/types";

const IMPORTANCES: Importance[] = ["always_on", "flexible", "deferrable"];

const IMPORTANCE_ACTIVE: Record<Importance, string> = {
  always_on: "bg-importance-always-on/20 text-importance-always-on border-importance-always-on/40",
  flexible: "bg-importance-flexible/20 text-importance-flexible border-importance-flexible/40",
  deferrable: "bg-importance-deferrable/20 text-importance-deferrable border-importance-deferrable/40",
};

/** Owner controls for one device, opened from the floor. Manual commands win over the engine (ENGINE.md §5). */
export function DeviceDetails({ meta, reading, onClose }: { meta: DeviceMeta; reading?: HubDeviceReading; onClose: () => void }) {
  const close = useSim((s) => s.kitchen?.config.operating_hours.close ?? "22:00");
  const updateDevice = useSim((s) => s.updateDevice);
  const { run, busy, error } = useAction();
  const { device } = meta;
  const state = reading?.state ?? device.state;
  const Icon = meta.icon;

  const command = (action: "on" | "off" | "start" | "restore") => run(() => transport.deviceCommand(device.device_id, { action }));

  // Starting limits for a new importance; the Builder (Phase 1) is where the owner tunes them.
  const limitsFor = (importance: Importance): ImportanceLimits =>
    importance === "flexible"
      ? { min_power_pct: meta.minPowerPct ?? 40, max_reduce_min: 30 }
      : importance === "deferrable"
        ? { max_delay_min: 60, must_finish_by: close }
        : {};

  return (
    <div className="w-full rounded-xl border bg-popover p-3 text-sm shadow-2xl">
      <div className="flex items-center gap-2">
        <span
          className="flex size-7 items-center justify-center rounded-md"
          style={{ background: `color-mix(in oklch, ${meta.color} 22%, transparent)`, color: meta.color }}
        >
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{device.name}</div>
          <div className="text-xs text-muted-foreground">
            {fmtKw(reading?.power_kw)} now · {DEVICE_STATE_LABEL[state]} · {fmtKw(device.rated_kw)} rated
          </div>
        </div>
        <Button variant="ghost" size="icon" className="size-7" aria-label="Close" onClick={onClose}>
          <X />
        </Button>
      </div>

      <div className="mt-3 text-xs text-muted-foreground">What WattWise may do</div>
      <div className="mt-1 grid grid-cols-3 gap-1">
        {IMPORTANCES.map((imp) => (
          <button
            key={imp}
            type="button"
            disabled={busy || imp === device.importance}
            onClick={() =>
              run(async () => updateDevice(await transport.setImportance(device.device_id, { importance: imp, limits: limitsFor(imp) })))
            }
            className={cn(
              "rounded-md border px-1.5 py-1 text-xs transition-colors",
              imp === device.importance ? IMPORTANCE_ACTIVE[imp] : "border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {IMPORTANCE_LABEL[imp]}
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => command(state === "off" ? "on" : "off")}>
          <Power /> {state === "off" ? "Turn on" : "Turn off"}
        </Button>
        {meta.isJob && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => command("start")}>
            <Play /> Start job
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => command("restore")}>
          <RotateCcw /> Back to auto
        </Button>
      </div>
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
        You always win: after a manual change, WattWise leaves this device alone for 30 minutes.
      </p>
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}
