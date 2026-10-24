import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { LoaderCircle, Minus, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fmtKw } from "@/lib/format";
import { IMPORTANCE_BADGE, IMPORTANCE_LABEL } from "@/lib/theme";
import { errorMessage } from "@/lib/utils";
import { useSim } from "@/store/sim";
import { transport } from "@/transport";
import type { Category, EquipmentType, ImportanceLimits, KitchenConfig } from "@/types";

const CATEGORIES: { id: Category; label: string }[] = [
  { id: "cooking", label: "Cooking" },
  { id: "refrigeration", label: "Refrigeration" },
  { id: "cooling", label: "Cooling" },
  { id: "water_heating", label: "Water heating" },
  { id: "lighting", label: "Lighting" },
  { id: "other", label: "Other" },
];
const MAX_COUNT = 5;
const PRESET_COUNT = 1; // "Demo Café": one of each type

function defaultLimits(t: EquipmentType, close: string): ImportanceLimits {
  switch (t.default_importance) {
    case "flexible":
      return { min_power_pct: t.min_power_pct ?? 40, max_reduce_min: 30 };
    case "deferrable":
      return { max_delay_min: 60, must_finish_by: close };
    case "always_on":
      return {};
  }
}

export function BuilderPage() {
  const navigate = useNavigate();
  const setKitchen = useSim((s) => s.setKitchen);
  const setStoreCatalog = useSim((s) => s.setCatalog);
  const clearRun = useSim((s) => s.clearRun);
  const [catalog, setCatalog] = useState<EquipmentType[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [name, setName] = useState("Demo Café");
  const [peakCap, setPeakCap] = useState("40");
  const [open, setOpen] = useState("10:00");
  const [close, setClose] = useState("22:00");
  const [seed, setSeed] = useState("42");
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    transport.getCatalog().then(
      (types) => {
        setCatalog(types);
        setStoreCatalog(types);
        setCounts(Object.fromEntries(types.map((t) => [t.type_id, PRESET_COUNT])));
      },
      (err) => setError(errorMessage(err)),
    );
  }, [setStoreCatalog]);

  const groups = useMemo(
    () => CATEGORIES.map((c) => ({ ...c, types: (catalog ?? []).filter((t) => t.category === c.id) })).filter((g) => g.types.length),
    [catalog],
  );
  const anyEquipment = Object.values(counts).some((n) => n > 0);
  const capKw = Number(peakCap);
  const capValid = peakCap !== "" && Number.isFinite(capKw) && capKw > 0;

  async function build() {
    if (!catalog) return;
    const config: KitchenConfig = {
      name,
      equipment: catalog.map((t) => ({
        type_id: t.type_id,
        count: counts[t.type_id] ?? 0,
        importance: t.default_importance,
        limits: defaultLimits(t, close),
      })),
      peak_cap_kw: capKw,
      operating_hours: { open, close },
      tariff_id: "", // STUB: no tariff list endpoint yet; the team records the tariff in DECISIONS.md
      seed: Number(seed) || 42,
    };
    setBuilding(true);
    setError(null);
    clearRun();
    try {
      await transport.createKitchen(config);
      setKitchen(await transport.getKitchen());
      navigate("/live");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBuilding(false);
    }
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-6 p-6 lg:grid-cols-[1fr_320px]">
      <div className="flex flex-col gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Kitchen Builder</h1>
          <p className="text-muted-foreground">Pick your equipment and how many of each. Every unit reports to one hub.</p>
        </div>
        {!catalog && !error && <p className="text-sm text-muted-foreground">Loading equipment…</p>}
        {groups.map((g) => (
          <Card key={g.id} className="gap-2 py-4">
            <CardHeader className="px-4">
              <CardTitle className="text-xs tracking-wide text-muted-foreground uppercase">{g.label}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col divide-y px-4">
              {g.types.map((t) => (
                <div key={t.type_id} className="flex items-center gap-3 py-2">
                  <div className="flex-1">
                    <div className="font-medium">{t.name}</div>
                    <div className="text-xs text-muted-foreground">{fmtKw(t.rated_kw)} rated</div>
                  </div>
                  <Badge className={IMPORTANCE_BADGE[t.default_importance]}>{IMPORTANCE_LABEL[t.default_importance]}</Badge>
                  <Stepper label={t.name} value={counts[t.type_id] ?? 0} onChange={(n) => setCounts((c) => ({ ...c, [t.type_id]: n }))} />
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
        {/* Phase 1: list every unit with its own importance + limits (flexible: min power % and max minutes;
            deferrable: max delay and finish-by). Open question: KitchenConfig sets importance per type, not per unit. */}
      </div>

      <Card className="h-fit gap-4 lg:sticky lg:top-6">
        <CardHeader>
          <CardTitle>Your kitchen</CardTitle>
          <CardDescription>Settings the engine has to respect</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Field id="name" label="Name">
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field id="peak-cap" label="Peak cap (kW)" hint="Your highest 15-minute average power. Demand charges are based on this.">
            <Input
              id="peak-cap"
              type="number"
              min={1}
              step={0.5}
              value={peakCap}
              aria-invalid={!capValid}
              onChange={(e) => setPeakCap(e.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field id="opens" label="Opens">
              <Input id="opens" type="time" value={open} onChange={(e) => setOpen(e.target.value)} />
            </Field>
            <Field id="closes" label="Closes">
              <Input id="closes" type="time" value={close} onChange={(e) => setClose(e.target.value)} />
            </Field>
          </div>
          <Field id="tariff" label="Tariff" hint="The preset list arrives once the API serves tariffs.">
            <Input id="tariff" disabled placeholder="Team's chosen tariff" />
          </Field>
          <Field id="seed" label="Seed" hint="Same seed, same run. Hidden in demo mode.">
            <Input id="seed" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
          </Field>
          <Button size="lg" disabled={!catalog || !capValid || !anyEquipment || building} onClick={build}>
            {building ? (
              <>
                <LoaderCircle className="animate-spin" /> Warming up 21 days of history…
              </>
            ) : (
              "Build kitchen"
            )}
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>
    </div>
  );
}

function Stepper({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex items-center gap-1">
      <Button variant="outline" size="icon" className="size-8" aria-label={`Fewer ${label}`} disabled={value <= 0} onClick={() => onChange(value - 1)}>
        <Minus />
      </Button>
      <span className="w-6 text-center tabular-nums">{value}</span>
      <Button
        variant="outline"
        size="icon"
        className="size-8"
        aria-label={`More ${label}`}
        disabled={value >= MAX_COUNT}
        onClick={() => onChange(value + 1)}
      >
        <Plus />
      </Button>
    </div>
  );
}

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
