import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { Bot, LoaderCircle, MapPin, Minus, Plus, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fmtKw } from "@/lib/format";
import { IMPORTANCE_BADGE, IMPORTANCE_LABEL } from "@/lib/theme";
import { errorMessage } from "@/lib/utils";
import { useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";
import type { Category, ClaudeAuthority, DeferrableLimits, EquipmentType, FlexibleLimits, Importance, ImportanceLimits, KitchenConfig } from "@/types";

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

const LOCATIONS = [{ label: "Marina, San Francisco", lat: 37.8, lon: -122.44 }];
const DEFAULT_AUTHORITY: ClaudeAuthority = {
  enabled: true,
  max_cap_overrun_kw: 3,
  max_extra_delay_min: 20,
  max_extra_reduce_min: 15,
  may_go_below_min_power: false,
};
/** Food safety (SIMULATION.md): refrigeration never goes below 50 % power, whatever the owner sets. */
const FOOD_SAFETY_MIN_PCT = 50;
const IMPORTANCES: Importance[] = ["always_on", "flexible", "deferrable"];

interface UnitSetting {
  importance: Importance;
  limits: ImportanceLimits;
}

function minPct(t: EquipmentType) {
  return t.category === "refrigeration" ? FOOD_SAFETY_MIN_PCT : 0;
}

/** Limits for a unit switched to `importance`: the catalog's default_limits when they fit, else sensible ones. */
function limitsFor(t: EquipmentType, importance: Importance, close: string): ImportanceLimits {
  if (importance === t.default_importance && t.default_limits) return structuredClone(t.default_limits);
  switch (importance) {
    case "flexible":
      return { min_power_pct: Math.max(40, minPct(t)), max_reduce_min: 30 };
    case "deferrable":
      return { max_delay_min: 60, must_finish_by: close };
    case "always_on":
      return {};
  }
}

const sameSetting = (a: UnitSetting, b: UnitSetting) => a.importance === b.importance && JSON.stringify(a.limits) === JSON.stringify(b.limits);

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
  const [locationIdx, setLocationIdx] = useState(0);
  const [preferences, setPreferences] = useState("");
  const [authority, setAuthority] = useState<ClaudeAuthority>(DEFAULT_AUTHORITY);
  // Per-unit overrides keyed by device id (`<type_id>_<n>`); units without one use the type's defaults.
  const [units, setUnits] = useState<Record<string, UnitSetting>>({});
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
  const typeDefault = (t: EquipmentType): UnitSetting => ({ importance: t.default_importance, limits: limitsFor(t, t.default_importance, close) });
  const unitList = (catalog ?? []).flatMap((t) =>
    Array.from({ length: counts[t.type_id] ?? 0 }, (_, i) => {
      const id = `${t.type_id}_${i + 1}`;
      return { id, name: `${t.name} ${i + 1}`, type: t, setting: units[id] ?? typeDefault(t) };
    }),
  );
  const setUnit = (id: string, setting: UnitSetting) => setUnits((u) => ({ ...u, [id]: setting }));
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
        limits: limitsFor(t, t.default_importance, close),
      })),
      peak_mode: "cap",
      peak_cap_kw: capKw,
      operating_hours: { open, close },
      location: LOCATIONS[locationIdx],
      owner_preferences: preferences.trim(),
      authority,
      tariff_id: "demo_tariff_v1", // STUB: no tariff list endpoint exists yet.
      seed: Number(seed) || 42,
    };
    setBuilding(true);
    setError(null);
    clearRun();
    try {
      await transport.createKitchen(config);
      // KitchenConfig sets importance per type; units that differ are set one by one once they exist.
      const overrides = unitList.filter((u) => !sameSetting(u.setting, typeDefault(u.type)));
      await Promise.all(overrides.map((u) => transport.setImportance(u.id, u.setting)));
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
        {unitList.length > 0 && (
          <Card className="gap-2 py-4">
            <CardHeader className="px-4">
              <CardTitle>Each unit</CardTitle>
              <CardDescription>How much WattWise may touch each unit. Always on is never touched.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col divide-y px-4">
              {unitList.map((u) => (
                <UnitRow key={u.id} name={u.name} type={u.type} setting={u.setting} close={close} onChange={(st) => setUnit(u.id, st)} />
              ))}
            </CardContent>
          </Card>
        )}

        <Card className="gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="flex items-center gap-2">
              <Bot className="size-4" /> Claude's authority
            </CardTitle>
            <CardDescription>
              When routine moves can't hold the cap, Claude may pick an option within these limits. Anything beyond them waits for you.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 px-4">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" className="size-4 accent-[var(--color-importance-flexible)]" checked={authority.enabled} onChange={(e) => setAuthority((a) => ({ ...a, enabled: e.target.checked }))} />
              Let Claude decide escalations on its own
            </label>
            <div className="grid gap-3 sm:grid-cols-3">
              <NumberField id="auth-overrun" label="Go over the cap by up to (kW)" value={authority.max_cap_overrun_kw} step={0.5} disabled={!authority.enabled} onChange={(v) => setAuthority((a) => ({ ...a, max_cap_overrun_kw: v }))} />
              <NumberField id="auth-delay" label="Extra delay (min)" value={authority.max_extra_delay_min} step={5} disabled={!authority.enabled} onChange={(v) => setAuthority((a) => ({ ...a, max_extra_delay_min: v }))} />
              <NumberField id="auth-reduce" label="Extra reduce time (min)" value={authority.max_extra_reduce_min} step={5} disabled={!authority.enabled} onChange={(v) => setAuthority((a) => ({ ...a, max_extra_reduce_min: v }))} />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="size-4" disabled={!authority.enabled} checked={authority.may_go_below_min_power} onChange={(e) => setAuthority((a) => ({ ...a, may_go_below_min_power: e.target.checked }))} />
              May go below a unit's minimum power
            </label>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <ShieldCheck className="size-3.5 text-lane-with" /> Refrigeration never goes below 50 % power, whatever you set here.
            </p>
          </CardContent>
        </Card>
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
          <Field id="location" label="Location" hint="The weather and events agents look around here.">
            <div className="flex items-center gap-2">
              <MapPin className="size-4 shrink-0 text-muted-foreground" />
              <select
                id="location"
                className="h-9 w-full rounded-md border bg-transparent px-2 text-sm"
                value={locationIdx}
                onChange={(e) => setLocationIdx(Number(e.target.value))}
              >
                {LOCATIONS.map((l, i) => (
                  <option key={l.label} value={i} className="bg-popover">
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
          </Field>
          <Field id="prefs" label="Your preferences" hint="Plain words for Claude, e.g. 'Keep the dining room cool during dinner.'">
            <textarea
              id="prefs"
              rows={3}
              className="w-full rounded-md border bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground"
              placeholder="Anything WattWise should know about how you run the kitchen"
              value={preferences}
              onChange={(e) => setPreferences(e.target.value)}
            />
          </Field>
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

function UnitRow({ name, type: t, setting, close, onChange }: { name: string; type: EquipmentType; setting: UnitSetting; close: string; onChange: (s: UnitSetting) => void }) {
  const floor = minPct(t);
  const flex = setting.limits as FlexibleLimits;
  const def = setting.limits as DeferrableLimits;
  return (
    <div className="flex flex-col gap-2 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex-1 font-medium">{name}</span>
        <div className="flex gap-1" role="radiogroup" aria-label={`${name} importance`}>
          {IMPORTANCES.map((imp) => (
            <button
              key={imp}
              type="button"
              role="radio"
              aria-checked={setting.importance === imp}
              onClick={() => onChange({ importance: imp, limits: limitsFor(t, imp, close) })}
              className={
                setting.importance === imp
                  ? `rounded-md border px-2 py-0.5 text-xs ${IMPORTANCE_BADGE[imp]}`
                  : "rounded-md border px-2 py-0.5 text-xs text-muted-foreground hover:bg-secondary"
              }
            >
              {IMPORTANCE_LABEL[imp]}
            </button>
          ))}
        </div>
      </div>
      {setting.importance === "flexible" && (
        <div className="grid items-center gap-3 text-xs sm:grid-cols-[1fr_160px]">
          <label className="flex items-center gap-2">
            <span className="w-28 shrink-0 text-muted-foreground">Min power {flex.min_power_pct}%</span>
            <input
              type="range"
              min={floor}
              max={100}
              step={5}
              value={flex.min_power_pct}
              aria-label={`${name} minimum power`}
              className="flex-1 accent-[var(--color-importance-flexible)]"
              onChange={(e) => onChange({ ...setting, limits: { ...flex, min_power_pct: Math.max(floor, Number(e.target.value)) } })}
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">Max</span>
            <Input type="number" min={0} step={5} className="h-7 w-16" value={flex.max_reduce_min} onChange={(e) => onChange({ ...setting, limits: { ...flex, max_reduce_min: Number(e.target.value) || 0 } })} />
            <span className="text-muted-foreground">min</span>
          </label>
          {floor > 0 && <span className="text-[11px] text-muted-foreground sm:col-span-2">Food safety: never below {floor}%.</span>}
        </div>
      )}
      {setting.importance === "deferrable" && (
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">Delay up to</span>
            <Input type="number" min={0} step={5} className="h-7 w-16" value={def.max_delay_min} onChange={(e) => onChange({ ...setting, limits: { ...def, max_delay_min: Number(e.target.value) || 0 } })} />
            <span className="text-muted-foreground">min</span>
          </label>
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">Finish by</span>
            <Input type="time" className="h-7 w-28" value={def.must_finish_by} onChange={(e) => onChange({ ...setting, limits: { ...def, must_finish_by: e.target.value } })} />
          </label>
        </div>
      )}
    </div>
  );
}

function NumberField({ id, label, value, step, disabled, onChange }: { id: string; label: string; value: number; step: number; disabled?: boolean; onChange: (v: number) => void }) {
  return (
    <Field id={id} label={label}>
      <Input id={id} type="number" min={0} step={step} value={value} disabled={disabled} onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))} />
    </Field>
  );
}
