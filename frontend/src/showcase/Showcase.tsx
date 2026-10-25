import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";
import { Bloom, EffectComposer, TiltShift2, ToneMapping } from "@react-three/postprocessing";
import { ToneMappingMode } from "postprocessing";
import type { Group } from "three";
import { Pause, Play, RotateCcw } from "lucide-react";
import { CameraRig, ORTHO_VIEWS } from "@/components/live/floor/LiveFloor";
import { BACKGROUND, INK, LANE_HEX, STATE_HEX } from "@/components/live/floor/palette";
import { placeDevices } from "@/components/live/floor/plan";
import { Restaurant } from "@/components/live/floor/Restaurant";
import { STAGE } from "@/components/live/floor/Scenery";
import { useDeviceMeta } from "@/hooks/useDeviceMeta";
import { cn } from "@/lib/utils";
import type { Lane } from "@/types";
import {
  CAP,
  DEMAND_USD_PER_KW,
  END_MIN,
  ENERGY_USD_PER_KWH,
  createShowcase,
  peakSoFarKw,
  stepShowcase,
  toTick,
} from "./model";

const MS_PER_SIM_MIN = 160; // 4 simulated hours in about 38 seconds
const PADDING = { top: 64, bottom: 14, left: 12, right: 12 };

const fmtTime = (m: number) => {
  const h = Math.floor(m / 60);
  return `Fri ${((h + 11) % 12) + 1}:${String(m % 60).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"}`;
};
const kw = (x: number) => `${x.toFixed(1)} kW`;

/** The public demo: the project's 3D floor in demo-mode style, driven by the small in-browser showcase model. */
export function Showcase() {
  const sim = useRef(createShowcase());
  const [version, setVersion] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [lane, setLane] = useState<Lane>("with");
  const [selected, setSelected] = useState<string | null>(null);
  const metas = useDeviceMeta();
  const placement = useMemo(() => placeDevices(metas), [metas]);
  const stage = useRef<Group>(null);
  const deviceRefs = useRef(new Map<string, Group>());

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      stepShowcase(sim.current);
      if (sim.current.done) setPlaying(false);
      setVersion((v) => v + 1);
    }, MS_PER_SIM_MIN);
    return () => clearInterval(timer);
  }, [playing]);

  const s = sim.current;
  // `version` changes every simulated minute; the model itself lives in the ref.
  const tick = useMemo(() => (s.t > s.lanes.with.block_start || s.done ? toTick(s, lane) : null), [version, lane, s]);
  const peakWithout = peakSoFarKw(s, s.lanes.without);
  const peakWith = peakSoFarKw(s, s.lanes.with);
  const peakLower = Math.max(0, peakWithout - peakWith);
  const kwhSaved = Math.max(0, s.lanes.without.energy_kwh - s.lanes.with.energy_kwh);
  const usdSaved = peakLower * DEMAND_USD_PER_KW + kwhSaved * ENERGY_USD_PER_KWH;
  const started = s.t > s.lanes.with.block_start || s.done;

  const toggle = () => {
    if (s.done) {
      sim.current = createShowcase();
      setVersion((v) => v + 1);
      setPlaying(true);
      return;
    }
    setPlaying((p) => !p);
  };
  const restart = () => {
    sim.current = createShowcase();
    setVersion((v) => v + 1);
  };

  return (
    <div className="flex min-h-dvh flex-col bg-[#0f1424] text-slate-100">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-3">
          <a href="../" className="flex size-10 items-center justify-center rounded-xl border-2 border-[#22223B] bg-[#168F84] text-lg shadow-[0_3px_0_#000]" aria-label="WattWise home">
            ⚡
          </a>
          <div>
            <h1 className="font-[Fredoka] text-lg font-semibold leading-tight sm:text-xl">Keep service running. Keep demand down.</h1>
            <p className="text-xs text-slate-400">Demo Café · Friday dinner rush · simplified demo, simulated data</p>
          </div>
        </div>
        <nav className="flex gap-1 text-sm font-semibold">
          <a className="rounded-lg px-3 py-1.5 text-slate-300 hover:bg-white/10" href="../">Home</a>
          <a className="rounded-lg px-3 py-1.5 text-slate-300 hover:bg-white/10" href="../pitch/">Slides</a>
        </nav>
      </header>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-white/10 px-4 py-3">
        <div className="min-w-[150px] text-2xl font-semibold tabular-nums">{fmtTime(Math.min(s.t, END_MIN))}</div>
        <button
          type="button"
          onClick={toggle}
          className="flex h-11 min-w-[124px] items-center justify-center gap-2 rounded-full bg-[#5EC4B6] px-5 text-base font-bold text-[#0f1424] shadow-[0_3px_0_#000] transition active:translate-y-0.5"
        >
          {playing ? <Pause className="size-5" /> : <Play className="size-5" />}
          {playing ? "Pause" : s.done ? "Replay" : started ? "Play" : "Start"}
        </button>
        <button type="button" onClick={restart} title="Back to 5 PM" aria-label="Back to 5 PM" className="rounded-full p-2 text-slate-300 hover:bg-white/10">
          <RotateCcw className="size-5" />
        </button>
        <div className="flex rounded-full bg-white/5 p-1" role="group" aria-label="Which kitchen to show">
          {(
            [
              ["with", "With WattWise", "bg-emerald-400/15 text-emerald-300"],
              ["without", "Without", "bg-red-400/15 text-red-300"],
            ] as const
          ).map(([value, label, on]) => (
            <button
              key={value}
              type="button"
              aria-pressed={lane === value}
              onClick={() => setLane(value)}
              className={cn("rounded-full px-4 py-2 text-sm font-bold transition", lane === value ? on : "text-slate-300 hover:text-white")}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <main className="grid flex-1 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="relative h-[58vh] min-h-[360px] lg:h-auto" style={{ background: BACKGROUND }}>
          <Canvas
            shadows="percentage"
            orthographic
            dpr={[1, 1.5]}
            camera={{ position: [34, 30, 36], zoom: 24, near: 0.1, far: 600 }}
            gl={{ antialias: false, powerPreference: "high-performance", preserveDrawingBuffer: true }}
            onPointerMissed={() => setSelected(null)}
          >
            <color attach="background" args={[BACKGROUND]} />
            <ambientLight intensity={1.1} color="#FFF6E9" />
            <hemisphereLight args={["#FFFFFF", "#E8B89A", 0.5]} />
            <directionalLight position={[26, 40, 30]} intensity={1.6} color="#FFF1DE" castShadow shadow-mapSize={[2048, 2048]} shadow-bias={-0.0004} shadow-normalBias={0.03}>
              <orthographicCamera attach="shadow-camera" args={[-45, 45, 45, -45, 1, 160]} />
            </directionalLight>
            <group ref={stage}>
              <Restaurant
                lane={lane}
                tick={tick}
                detail="full"
                placement={placement}
                selected={selected}
                onSelect={setSelected}
                deviceRefs={deviceRefs}
                labels
                focus={false}
                spotlight={null}
              />
            </group>
            <ContactShadows
              position={[(STAGE.x0 + STAGE.x1) / 2, -0.03 - STAGE.depth - 0.02, (STAGE.y0 + STAGE.y1) / 2]}
              scale={[STAGE.x1 - STAGE.x0 + 3, STAGE.y1 - STAGE.y0 + 3]}
              far={1.2}
              blur={2.6}
              opacity={0.45}
              resolution={512}
              color={INK}
              frames={1}
            />
            <CameraRig stage={stage} fitKey="single" frames={null} padding={PADDING} margin={1.02} view={ORTHO_VIEWS.iso} />
            <OrbitControls makeDefault enablePan={false} enableDamping zoomSpeed={0.7} />
            <EffectComposer multisampling={4}>
              <Bloom mipmapBlur intensity={0.7} luminanceThreshold={1} luminanceSmoothing={0.2} radius={0.6} />
              <ToneMapping mode={ToneMappingMode.NEUTRAL} />
              <TiltShift2 blur={0.06} taper={0.6} />
            </EffectComposer>
          </Canvas>
          <div className="pointer-events-none absolute right-2.5 top-2.5 grid grid-cols-2 gap-x-3 gap-y-0.5 rounded-xl border-2 border-[#22223B] bg-white/90 px-2.5 py-1.5 text-[10px] font-semibold text-[#22223B] shadow-[0_2px_0_#22223B]">
            {(
              [
                ["on", "Running"],
                ["reduced", "Reduced"],
                ["waiting", "Delayed"],
                ["off", "Off"],
              ] as const
            ).map(([state, label]) => (
              <span key={state} className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm" style={{ background: STATE_HEX[state] }} />
                {label}
              </span>
            ))}
          </div>
          {!started && (
            <div className="pointer-events-none absolute inset-x-0 bottom-6 flex justify-center">
              <span className="rounded-full bg-[#0f1424]/85 px-4 py-2 text-sm font-semibold">Press Start to run 5 PM to 9 PM</span>
            </div>
          )}
        </div>

        <aside className="flex flex-col gap-3 border-white/10 p-3 lg:border-l">
          <Card title="15-minute peak tonight" hint={`The highest 15 minutes sets the demand charge. Cap ${CAP} kW.`}>
            <PeakRow label="Without WattWise" value={peakWithout} color={LANE_HEX.without} />
            <PeakRow label="With WattWise" value={peakWith} color={LANE_HEX.with} />
            <p className={cn("mt-1 text-sm font-semibold", peakLower > 0.05 ? "text-emerald-300" : "text-slate-400")}>
              {peakLower > 0.05 ? `${kw(peakLower)} lower with WattWise` : "Same so far: the rush hasn't started"}
            </p>
          </Card>
          <Card title="Saved tonight" hint="Illustrative tariff: $20/kW monthly + $8/kW peak-period demand, $0.38/kWh.">
            <div className="font-[Fredoka] text-4xl font-semibold text-emerald-300 tabular-nums">${Math.round(usdSaved).toLocaleString("en-US")}</div>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-lg bg-white/5 p-2">
                <dt className="text-xs text-slate-400">Energy saved</dt>
                <dd className="font-semibold tabular-nums">{kwhSaved.toFixed(1)} kWh</dd>
              </div>
              <div className="rounded-lg bg-white/5 p-2">
                <dt className="text-xs text-slate-400">Peak shaved</dt>
                <dd className="font-semibold tabular-nums">{kw(peakLower)}</dd>
              </div>
            </dl>
          </Card>
          <p className="mt-auto px-1 text-[11px] leading-relaxed text-slate-500">
            Simplified public demo: simulated appliances and a small rule-based controller in your browser, not the WattWise
            engine. Not measured savings.
          </p>
        </aside>
      </main>
    </div>
  );
}

function Card({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.04] p-3.5">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="mb-2 text-[11px] text-slate-400">{hint}</p>
      {children}
    </section>
  );
}

function PeakRow({ label, value, color }: { label: string; value: number; color: string }) {
  const scale = Math.max(CAP * 1.35, value);
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs">
        <span className="text-slate-300">{label}</span>
        <span className="font-semibold tabular-nums" style={{ color: value > CAP + 0.05 ? "#FF8FA3" : undefined }}>
          {kw(value)}
        </span>
      </div>
      <div className="relative mt-1 h-2.5 rounded-full bg-white/10">
        <div className="h-full rounded-full transition-[width] duration-300" style={{ width: `${(value / scale) * 100}%`, background: color }} />
        <div className="absolute -top-1 h-4.5 w-0.5 bg-white/80" style={{ left: `${(CAP / scale) * 100}%` }} title={`Cap ${CAP} kW`} />
      </div>
    </div>
  );
}
