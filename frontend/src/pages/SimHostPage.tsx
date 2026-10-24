import { Activity, CircleAlert, RadioTower, ServerCog } from "lucide-react";
import type { Device, DevicePhysical, Lane } from "@/types";
import { isFixtureHub, useDevices, useHubHost, type HubConnectionState } from "@/data";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function SimHostPage() {
  const status = useHubHost();
  const without = useDevices("without");
  const withControl = useDevices("with");

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 p-4 sm:p-6 lg:p-8">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-medium tracking-[0.18em] text-primary uppercase">
            <ServerCog className="size-4" /> Dedicated simulation host
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Browser hub</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Keep this tab open during the demo. It runs both kitchen lanes and reports every appliance reading to FastAPI.
          </p>
        </div>
        <ConnectionBadge connection={status.connection} />
      </header>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Hub status" value={status.message} icon={RadioTower} />
        <Metric label="Last tick" value={status.tickId ? `#${status.tickId}` : "Waiting"} icon={Activity} />
        <Metric label="Simulation time" value={status.simTs ? new Date(status.simTs).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "—"} />
        <Metric label="Mode" value={isFixtureHub ? "Fixture replay · fake data" : "FastAPI /ws/hub"} />
      </section>

      {status.connection === "host_taken" && (
        <div className="flex items-start gap-3 rounded-[22px] border-2 border-[#22223B] bg-[#FFF0BA] p-4 text-sm text-[#5F4200] shadow-[0_4px_0_#22223B]">
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-[#8A5A00]" />
          <div><strong>Host already claimed.</strong> Close the other <code>/sim</code> tab, then reload this page.</div>
        </div>
      )}

      <div className="grid min-w-0 gap-5 xl:grid-cols-2">
        <LanePanel lane="without" devices={without} />
        <LanePanel lane="with" devices={withControl} />
      </div>
    </div>
  );
}

function ConnectionBadge({ connection }: { connection: HubConnectionState }) {
  const good = connection === "connected";
  return (
    <Badge
      variant="outline"
      className={cn(
        "w-fit gap-2 px-3 py-1.5",
        good ? "border-[#22223B] bg-[#DFF6F3] text-[#167D74]" : "border-[#22223B] bg-[#FFF0BA] text-[#8A5A00]",
      )}
    >
      <span className={cn("size-2 rounded-full", good ? "bg-primary shadow-[0_0_10px_var(--primary)]" : "bg-amber-300")} />
      {connection.replace("_", " ")}
    </Badge>
  );
}

function Metric({ label, value, icon: Icon }: { label: string; value: string; icon?: typeof Activity }) {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="flex items-start justify-between gap-3 px-4">
        <div className="min-w-0">
          <div className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{label}</div>
          <div className="mt-1 truncate text-sm font-semibold tabular-nums">{value}</div>
        </div>
        {Icon && <Icon className="size-4 shrink-0 text-primary" />}
      </CardContent>
    </Card>
  );
}

function LanePanel({ lane, devices }: { lane: Lane; devices: Device[] }) {
  const total = devices.reduce((sum, device) => sum + device.power_kw, 0);
  return (
    <Card className="min-w-0 gap-4 py-5">
      <CardHeader className="px-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>{lane === "with" ? "With WattWise" : "Without WattWise"}</CardTitle>
            <CardDescription>{devices.length || "No"} device readings received</CardDescription>
          </div>
          <div className={cn("text-xl font-semibold tabular-nums", lane === "with" ? "text-lane-with" : "text-lane-without")}>
            {total.toFixed(2)} kW
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-2 px-3 sm:grid-cols-2 sm:px-5">
        {devices.length ? devices.map((device) => <DeviceRow key={device.device_id} device={device} />) : (
          <div className="col-span-full rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
            Waiting for <code>sim_build</code> and the first tick…
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DeviceRow({ device }: { device: Device }) {
  const active = device.power_kw > 0;
  return (
    <div className={cn(
      "rounded-2xl border-2 border-[#22223B] bg-[#FFF6E9] p-3 transition-colors",
      active && "bg-[#DFF6F3]",
      device.state === "waiting" && "bg-[#FFF0BA]",
    )}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{device.name}</div>
          <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className={cn("size-1.5 rounded-full", active ? "bg-primary shadow-[0_0_7px_var(--primary)]" : "bg-muted-foreground/40")} />
            {device.state.replace("_", " ")}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-sm font-semibold tabular-nums">{device.power_kw.toFixed(2)} kW</div>
          <div className="text-[10px] text-muted-foreground tabular-nums">{device.power_pct}% of rated</div>
        </div>
      </div>
      {device.physical && <Physical physical={device.physical} />}
    </div>
  );
}

const PHYSICAL_LABELS: Record<string, string> = {
  indoor_temp_c: "Room",
  box_temp_c: "Temperature",
  dirty_racks: "Dirty racks",
  ice_level_pct: "Ice",
  job_remaining_min: "Job left",
  orders_in_progress: "Orders",
};

const physicalValue = (key: string, value: unknown) => {
  if (typeof value !== "number") return String(value);
  if (key.endsWith("_temp_c")) return `${value.toFixed(1)} °C`;
  if (key.endsWith("_pct")) return `${Math.round(value)}%`;
  if (key.endsWith("_min")) return `${Math.round(value)} min`;
  return String(Math.round(value));
};

function Physical({ physical }: { physical: DevicePhysical }) {
  const entries = Object.entries(physical).filter(([, value]) => value != null);
  return (
    <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t pt-2 text-[10px] text-muted-foreground">
      {entries.map(([key, value]) => (
        <span key={key}>{PHYSICAL_LABELS[key] ?? key}: <b className="font-medium text-foreground">{physicalValue(key, value)}</b></span>
      ))}
    </div>
  );
}
