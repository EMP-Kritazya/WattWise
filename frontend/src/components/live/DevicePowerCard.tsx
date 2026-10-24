import { useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useDeviceMeta } from "@/hooks/useDeviceMeta";
import { fmtKw } from "@/lib/format";
import { useDashboardStore as useSim } from "@/data";
import type { Lane } from "@/types";

/** Where the power is going right now, per device, as the hub reports it. kW only: no percentages computed here. */
export function DevicePowerCard() {
  const [lane, setLane] = useState<Lane>("with");
  const tick = useSim((s) => s.latest[lane]);
  const metas = useDeviceMeta();

  const slices = useMemo(() => {
    const power = new Map((tick?.hub.devices ?? []).map((r) => [r.device_id, r.power_kw] as const));
    return metas
      .map((m) => ({ id: m.device.device_id, name: m.device.name, color: m.color, kw: power.get(m.device.device_id) ?? 0 }))
      .sort((a, b) => b.kw - a.kw);
  }, [tick, metas]);

  return (
    <Card className="min-w-0 gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex items-center gap-2">
          Power by device
          <span className="flex items-center gap-1 text-xs font-normal text-lane-with">
            <span className="size-1.5 animate-pulse rounded-full bg-lane-with" /> Live
          </span>
        </CardTitle>
        <CardDescription>From the hub · simulated</CardDescription>
        <ToggleGroup type="single" variant="outline" size="sm" className="mt-1" value={lane} onValueChange={(v) => v && setLane(v as Lane)}>
          <ToggleGroupItem value="with" className="px-3">
            With
          </ToggleGroupItem>
          <ToggleGroupItem value="without" className="px-3">
            Without
          </ToggleGroupItem>
        </ToggleGroup>
      </CardHeader>
      <CardContent className="flex items-center gap-4 px-4">
        <div className="relative size-36 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={slices.filter((s) => s.kw > 0)}
                dataKey="kw"
                nameKey="name"
                innerRadius="70%"
                outerRadius="100%"
                paddingAngle={2}
                stroke="none"
                isAnimationActive={false}
              >
                {slices
                  .filter((s) => s.kw > 0)
                  .map((s) => (
                    <Cell key={s.id} fill={s.color} />
                  ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-semibold tabular-nums">{fmtKw(tick?.hub.total_kw)}</span>
            <span className="text-[11px] text-muted-foreground">Total</span>
          </div>
        </div>
        <ul className="flex max-h-44 min-w-0 flex-1 flex-col gap-1 overflow-y-auto pr-1 text-xs">
          {slices.map((s) => (
            <li key={s.id} className="flex items-center gap-2">
              <span className="size-2 shrink-0 rounded-full" style={{ background: s.color }} />
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{s.name}</span>
              <span className="tabular-nums">{fmtKw(s.kw)}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
