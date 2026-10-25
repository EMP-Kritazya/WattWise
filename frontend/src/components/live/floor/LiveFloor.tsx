import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, PerspectiveCamera } from "@react-three/drei";
import { Bloom, EffectComposer, ToneMapping } from "@react-three/postprocessing";
import { ToneMappingMode } from "postprocessing";
import { Box3, Vector3, type Group, type OrthographicCamera } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { Box, Crosshair, Eye, Focus, Map as MapIcon, Maximize2, Store, Tags, type LucideIcon } from "lucide-react";
import { WarningBanner } from "@/components/live/WarningBanner";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useDeviceMeta } from "@/hooks/useDeviceMeta";
import { fmtAction, fmtKw } from "@/lib/format";
import { cn } from "@/lib/utils";
import { requestSurge, useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";
import { DemoBar, newestDecision } from "./Hud";
import { BACKGROUND, STATE_HEX } from "./palette";
import { placeDevices, type Placement } from "./plan";
import { Restaurant } from "./Restaurant";
import type { DecisionSpotlight } from "./Device3D";
import { DemandSummary, OperationsPanel } from "./OperationsPanel";
import { ToyBoxRail } from "./ToyBoxRail";

type Vec3 = [number, number, number];
type Mode = "with" | "without" | "compare";
type View = "iso" | "top" | "street" | "pov";

const VIEW_ORDER: View[] = ["iso", "top", "street", "pov"];
const VIEW_UI: Record<View, { label: string; icon: LucideIcon }> = {
  iso: { label: "Isometric", icon: Box },
  top: { label: "Top-down", icon: MapIcon },
  street: { label: "Street", icon: Store },
  pov: { label: "POV", icon: Eye },
};

interface Limits {
  minPolar: number;
  maxPolar: number;
  minAzimuth: number;
  maxAzimuth: number;
}

/** Orthographic views: direction from the target toward the camera, and how far the viewer may orbit. */
const ORTHO_VIEWS: Record<"iso" | "top", { dir: Vector3; limits: Limits }> = {
  iso: { dir: new Vector3(34, 30, 36).normalize(), limits: { minPolar: 0.55, maxPolar: 1.2, minAzimuth: 0.25, maxAzimuth: 1.35 } },
  // Straight down, back wall at the top of the screen (the tiny z keeps the orientation defined).
  top: {
    dir: new Vector3(0, 1, 0.0005).normalize(),
    limits: { minPolar: 0, maxPolar: 0.0006, minAzimuth: -Infinity, maxAzimuth: Infinity },
  },
};

/** Perspective views: where the camera flies in from, where it settles, and what it looks at. */
const POSES: Record<"street" | "pov", { from: Vec3; pos: Vec3; target: Vec3; fov: number }> = {
  // From above the street in front, looking down (~30°) over the dining room into the kitchen and back rooms.
  street: { from: [11, 16, 30], pos: [10.5, 10, 21], target: [10, 0.4, 4.5], fov: 44 },
  // A diner's eyes near the front of the dining room, looking through the pass into the kitchen.
  pov: { from: [9.3, 6, 18], pos: [9.3, 1.2, 12.4], target: [6.2, 1.0, 2.2], fov: 58 },
};

/**
 * Both lanes at once. On a wide canvas they sit in a row ("with" to the right, same depth); on a narrower one they
 * stack ("without" behind, "with" in front), which makes both much bigger. Orthographic, so depth never shrinks them.
 */
const COMPARE_LAYOUT: Record<"row" | "column", { without: Vec3; with: Vec3 }> = {
  row: { without: [0, 0, 0], with: [21, 0, -21] },
  column: { without: [-21, 0, -21], with: [0, 0, 0] },
};
const FOLLOW_HOLD_MS = 4500;
const FOLLOW_COOLDOWN_MS = 9000;

/** A quiet spatial overview beside authoritative appliance readings and demand comparison. */
export function LiveFloor({ demo, onDemoChange }: { demo: boolean; onDemoChange: (on: boolean) => void }) {
  const metas = useDeviceMeta();
  const placement = useMemo(() => placeDevices(metas), [metas]);
  const [mode, setMode] = useState<Mode>("with");
  const [view, setView] = useState<View>("iso");
  const [labels, setLabels] = useState(true);
  // The Toy Box restaurant is the judge-facing default; Equipment focus remains available for isolating appliances.
  const [focus, setFocus] = useState(false);
  const [follow, setFollow] = useState(false);
  const perspective = view === "street" || view === "pov";
  // Side by side only works from above.
  useEffect(() => {
    if (mode === "compare" && perspective) setView("iso");
  }, [mode, perspective]);
  const [selected, setSelected] = useState<string | null>(null);
  const [autoFocus, setAutoFocus] = useState<string | null>(null);
  const withTick = useSim((s) => s.latest.with);
  const withoutTick = useSim((s) => s.latest.without);
  const feed = useSim((s) => s.feed);
  const deviceRefs = useRef(new Map<string, Group>());
  const lastFocusAt = useRef(0);

  // Follow decisions: fly to the device WattWise just acted on, hold, then pull back.
  const newest = useMemo(() => newestDecision(feed), [feed]);
  const newestKey = newest ? `${newest.decision.decision_id}:${newest.decision.status}` : null;
  const [spotlightEvent, setSpotlightEvent] = useState<typeof newest>(null);
  useEffect(() => {
    if (!newest || newest.decision.status !== "executed") return;
    setSpotlightEvent(newest);
    const timer = setTimeout(() => setSpotlightEvent(null), 6500);
    return () => clearTimeout(timer);
  }, [newestKey]);
  const spotlight = useMemo<DecisionSpotlight | null>(() => {
    if (!spotlightEvent) return null;
    const decision = spotlightEvent.decision;
    const name = metas.find((meta) => meta.device.device_id === decision.device_id)?.device.name ?? decision.device_id;
    return {
      deviceId: decision.device_id,
      title: `${name} · ${fmtAction(decision.action, decision.value)}`,
      detail: `15-min peak ${fmtKw(decision.effect.peak_before_kw)} → ${fmtKw(decision.effect.peak_after_kw)}`,
    };
  }, [spotlightEvent, metas]);
  useEffect(() => {
    if (!newest || !follow || mode !== "with" || selected) return;
    if (newest.decision.status !== "executed") return;
    if (Date.now() - lastFocusAt.current < FOLLOW_COOLDOWN_MS) return;
    lastFocusAt.current = Date.now();
    setAutoFocus(newest.decision.device_id);
    // Only a new decision (or a new status for it) moves the camera, not every feed update.
  }, [newestKey]);
  // Pull back after a while, and straight away if following is switched off or the view changes.
  useEffect(() => {
    if (!autoFocus) return;
    const t = setTimeout(() => setAutoFocus(null), FOLLOW_HOLD_MS);
    return () => clearTimeout(t);
  }, [autoFocus]);
  useEffect(() => {
    if (!follow || mode !== "with") setAutoFocus(null);
  }, [follow, mode]);

  // Reserve a small inset for labels; operational information lives outside the canvas.
  // With labels on, leave headroom above the building for the stacked appliance labels; the legend sits at the bottom.
  const padding = useMemo(() => ({ top: labels && mode !== "compare" ? 130 : 20, bottom: 44, left: 16, right: 16 }), [labels, mode]);
  const container = useRef<HTMLDivElement>(null);
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect;
      setWide(width / Math.max(1, height - padding.top - padding.bottom) > 1.9);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [padding]);
  const compare = COMPARE_LAYOUT[wide ? "row" : "column"];

  const focusId = mode === "compare" || perspective ? null : autoFocus;
  const frames = useMemo(() => {
    const focus = focusId ? focusBoxFor(placement, focusId) : null;
    if (focus) return [focus];
    if (mode !== "compare") return [SINGLE_BOX];
    return [compare.without, compare.with].map((o) => SINGLE_BOX.clone().translate(new Vector3(...o)));
  }, [placement, focusId, mode, compare]);

  useDemoKeys(demo, {
    compare: () => setMode((m) => (m === "compare" ? "with" : "compare")),
    follow: () => setFollow((f) => !f),
    view: () => setView((v) => VIEW_ORDER[(VIEW_ORDER.indexOf(v) + 1) % VIEW_ORDER.length]),
    labels: () => setLabels((l) => !l),
    exit: () => onDemoChange(false),
  });

  const shared = { placement, selected, onSelect: setSelected, deviceRefs, labels, focus };

  return (
    <section
      className={cn(
        "flex flex-col overflow-hidden border-2 border-[#22223B] bg-[#0f1424] text-slate-100",
        demo ? "fixed inset-0 z-40 overflow-y-auto" : "rounded-[22px] shadow-[0_6px_0_#22223B]",
      )}
      aria-label="Live kitchen simulation"
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div>
          <h2 className="text-lg font-semibold">Keep service running. Keep demand down.</h2>
          <p className="text-xs text-slate-400">Watch appliance status → see the engine’s action → compare demand.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup type="single" size="sm" value={mode} onValueChange={(v) => v && setMode(v as Mode)}>
            <ToggleGroupItem value="with" className="px-3 data-[state=on]:bg-emerald-400/15 data-[state=on]:text-emerald-300">
              With WattWise
            </ToggleGroupItem>
            <ToggleGroupItem value="without" className="px-3 data-[state=on]:bg-red-400/15 data-[state=on]:text-red-300">
              Without
            </ToggleGroupItem>
            <ToggleGroupItem value="compare" className="px-3">
              Side by side
            </ToggleGroupItem>
          </ToggleGroup>
          <Button
            size="sm"
            variant="ghost"
            className={cn("h-8", focus ? "bg-emerald-400/15 text-emerald-300" : "text-slate-400")}
            title="Hide furniture so only the appliances stand out"
            aria-pressed={focus}
            onClick={() => setFocus((f) => !f)}
          >
            <Focus /> Equipment focus {focus ? "on" : "off"}
          </Button>
          <details className="relative">
            <summary className="cursor-pointer px-3 py-2 text-xs text-slate-400">View options</summary>
            <div className="absolute right-0 top-full z-[90] flex w-80 flex-wrap gap-2 rounded-lg border bg-slate-900 p-3">
              {" "}
              <ToggleGroup type="single" size="sm" value={view} onValueChange={(v) => v && setView(v as View)}>
                {VIEW_ORDER.map((v) => {
                  const { label, icon: Icon } = VIEW_UI[v];
                  const off = mode === "compare" && (v === "street" || v === "pov");
                  return (
                    <ToggleGroupItem key={v} value={v} disabled={off} className="gap-1.5 px-2.5" title={`${label} view (V cycles)`}>
                      <Icon className="size-3.5" />
                      <span>{label}</span>
                    </ToggleGroupItem>
                  );
                })}
              </ToggleGroup>
              <Button
                size="sm"
                variant="ghost"
                className={cn("h-8", labels ? "text-emerald-300" : "text-white/50")}
                title="Show or hide the labels on the floor (L)"
                onClick={() => setLabels((l) => !l)}
              >
                <Tags /> Labels {labels ? "on" : "off"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={perspective || mode === "compare"}
                className={cn("h-8", follow ? "text-emerald-300" : "text-white/50")}
                title="Fly the camera to each decision (F)"
                onClick={() => setFollow((f) => !f)}
              >
                <Crosshair /> Follow {follow ? "on" : "off"}
              </Button>
            </div>
          </details>{" "}
          {!demo && (
            <Button size="sm" variant="ghost" className="h-8" title="Full-screen demo mode" onClick={() => onDemoChange(true)}>
              <Maximize2 /> Demo mode
            </Button>
          )}
        </div>
      </header>
      {demo && (
        <div className="p-3">
          <DemoBar onExit={() => onDemoChange(false)} />
          <WarningBanner />
        </div>
      )}
      {!demo && <DemandSummary />}
      <div
        className={cn(
          "grid min-h-0",
          demo ? "flex-1 lg:min-h-[560px] lg:grid-cols-[minmax(0,1fr)_370px]" : "lg:h-[620px] lg:grid-cols-[minmax(0,1fr)_360px]",
        )}
      >
        <div
          ref={container}
          className={cn("relative min-w-0 overflow-hidden", demo ? "min-h-[400px] lg:min-h-[460px]" : "h-[420px] lg:h-[620px]")}
          style={{ background: BACKGROUND }}
        >
          <Canvas
            shadows
            orthographic
            dpr={[1, 1.5]}
            camera={{ position: [34, 30, 36], zoom: 24, near: 0.1, far: 600 }}
            gl={{ antialias: false, powerPreference: "high-performance" }}
            onPointerMissed={() => setSelected(null)}
          >
            <color attach="background" args={[BACKGROUND]} />
            {/* Toy Box lighting: a soft warm fill and one warm key light with soft shadows (toon shading does the rest). */}
            <ambientLight intensity={1.1} color="#FFF6E9" />
            <hemisphereLight args={["#FFFFFF", "#E8B89A", 0.5]} />
            <directionalLight
              position={[26, 40, 30]}
              intensity={1.6}
              color="#FFF1DE"
              castShadow
              shadow-mapSize={[2048, 2048]}
              shadow-bias={-0.0004}
              shadow-normalBias={0.03}
            >
              <orthographicCamera attach="shadow-camera" args={[-45, 45, 45, -45, 1, 160]} />
            </directionalLight>

            {mode === "compare" ? (
              <>
                <Restaurant lane="without" tick={withoutTick} detail="compact" position={compare.without} spotlight={null} {...shared} />
                <Restaurant lane="with" tick={withTick} detail="compact" position={compare.with} spotlight={spotlight} {...shared} />
              </>
            ) : (
              <Restaurant
                lane={mode}
                tick={mode === "with" ? withTick : withoutTick}
                detail="full"
                spotlight={mode === "with" ? spotlight : null}
                {...shared}
              />
            )}
            {perspective ? (
              <>
                <PerspectiveCamera makeDefault fov={POSES[view].fov} near={0.05} far={500} position={POSES[view].from} />
                <PerspectiveRig pose={POSES[view]} />
              </>
            ) : (
              <CameraRig frames={frames} padding={padding} margin={focusId ? 1.15 : 1.03} view={ORTHO_VIEWS[view]} />
            )}

            {/* Rotation limits are set by the rigs, per view, once the camera arrives. */}
            <OrbitControls makeDefault enablePan={false} enableDamping zoomSpeed={0.7} />

            <EffectComposer multisampling={4}>
              {/* High threshold: only status lights, status pads and working heat elements glow, nothing else. */}
              <Bloom mipmapBlur intensity={0.7} luminanceThreshold={1} luminanceSmoothing={0.2} radius={0.6} />
              <ToneMapping mode={ToneMappingMode.NEUTRAL} />
            </EffectComposer>
          </Canvas>

          {/* Below dialogs (z-50) so it never covers Approve / Decline. */}
          <div className="pointer-events-none absolute bottom-3 left-3 z-[45] flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-slate-950/85 px-3 py-2 text-xs text-slate-300">
            {(
              [
                ["on", "Running"],
                ["reduced", "Reduced by WattWise"],
                ["waiting", "Waiting (delayed)"],
                ["off", "Off"],
              ] as const
            ).map(([state, label]) => (
              <span key={state} className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm" style={{ background: STATE_HEX[state] }} />
                {label}
              </span>
            ))}
            <span className="text-slate-500">· {mode === "compare" ? "same customers in both" : "click an appliance for details"} · simulated</span>
          </div>
        </div>
        {demo ? <ToyBoxRail /> : <OperationsPanel mode={mode} selected={selected} onSelect={setSelected} />}
      </div>
    </section>
  );
}

/** The building, roof pad and the front sidewalk with its lamps (the diorama's earth edge may bleed off-frame). */
const SINGLE_BOX = new Box3(new Vector3(-1.2, -0.3, -1.2), new Vector3(25.4, 3.2, 16.2));

interface Padding {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/**
 * Frames boxes exactly as they project on screen (orthographic, any orbit angle), centred in the part of the canvas
 * the HUD leaves free, and eases the camera there. Once it arrives it lets go, so the viewer can still orbit and zoom.
 */
const CAMERA_DISTANCE = 80; // orthographic: distance only matters for clipping

function applyLimits(controls: OrbitControlsImpl, l: Limits) {
  controls.minPolarAngle = l.minPolar;
  controls.maxPolarAngle = l.maxPolar;
  controls.minAzimuthAngle = l.minAzimuth;
  controls.maxAzimuthAngle = l.maxAzimuth;
}
const FREE: Limits = { minPolar: 0, maxPolar: Math.PI, minAzimuth: -Infinity, maxAzimuth: Infinity };

function CameraRig({
  frames,
  padding,
  margin,
  view,
}: {
  frames: Box3[];
  padding: Padding;
  margin: number;
  view: { dir: Vector3; limits: Limits };
}) {
  const camera = useThree((s) => s.camera) as OrthographicCamera;
  const controls = useThree((s) => s.controls) as OrbitControlsImpl | null;
  const goal = useRef<{ target: Vector3; zoom: number; dir: Vector3 } | null>(null);
  const request = useRef({ frames, padding, margin, view, version: 0 });
  const computedFor = useRef({ version: -1, width: 0, height: 0 });

  useEffect(() => {
    request.current = { frames, padding, margin, view, version: request.current.version + 1 };
  }, [frames, padding, margin, view]);

  useFrame(({ size }, dt) => {
    if (!controls) return;
    // Re-fit when asked to, or when the canvas changes size (entering demo mode, resizing the window).
    const req = request.current;
    const done = computedFor.current;
    if (done.version !== req.version || done.width !== size.width || done.height !== size.height) {
      // Keep the viewer's own orbit angle in the isometric view; snap to the view's direction otherwise.
      const current = camera.position.clone().sub(controls.target).normalize();
      const keepAngle = req.view.limits.maxPolar > 0.01 && current.y > 0.3 && current.y < 0.95;
      const dir = keepAngle && done.version >= 0 && goal.current === null ? current : req.view.dir;
      goal.current = { ...fitGoal(dir, req.frames, req.padding, req.margin, size.width, size.height), dir };
      computedFor.current = { version: req.version, width: size.width, height: size.height };
      applyLimits(controls, FREE); // let the camera travel; the view's limits apply on arrival
    }
    const g = goal.current;
    if (!g) return;
    const k = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 1 - Math.exp(-dt * 3.5);
    const dir = camera.position.clone().sub(controls.target).normalize().lerp(g.dir, k).normalize();
    controls.target.lerp(g.target, k);
    camera.position.copy(controls.target).addScaledVector(dir, CAMERA_DISTANCE);
    camera.zoom += (g.zoom - camera.zoom) * k;
    camera.updateProjectionMatrix();
    controls.update();
    if (controls.target.distanceTo(g.target) < 0.01 && Math.abs(camera.zoom - g.zoom) < 0.01 && dir.angleTo(g.dir) < 0.002) {
      // Land exactly on the view direction (matters for top-down, where a tiny leftover tilt would rotate the plan).
      camera.position.copy(controls.target).addScaledVector(g.dir, CAMERA_DISTANCE);
      goal.current = null;
      applyLimits(controls, req.view.limits);
      controls.update();
    }
  });
  return null;
}

/** Flies a perspective camera to a pose, then lets the viewer look around it a little. */
function PerspectiveRig({ pose }: { pose: { pos: Vec3; target: Vec3 } }) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as OrbitControlsImpl | null;
  const arrived = useRef(false);
  useEffect(() => {
    arrived.current = false;
    if (controls) applyLimits(controls, FREE);
  }, [pose, controls]);
  useFrame((_, dt) => {
    if (!controls || arrived.current) return;
    const k = 1 - Math.exp(-dt * 2.5);
    const pos = new Vector3(...pose.pos);
    camera.position.lerp(pos, k);
    controls.target.lerp(new Vector3(...pose.target), k);
    controls.update();
    if (camera.position.distanceTo(pos) < 0.02) {
      arrived.current = true;
      const az = controls.getAzimuthalAngle();
      const po = controls.getPolarAngle();
      applyLimits(controls, {
        minPolar: po - 0.35,
        maxPolar: Math.min(Math.PI / 2 + 0.1, po + 0.3),
        minAzimuth: az - 0.7,
        maxAzimuth: az + 0.7,
      });
    }
  });
  return null;
}

/** Target and zoom that show `frames` as large as possible inside the canvas area the HUD leaves free. */
function fitGoal(dir: Vector3, frames: Box3[], padding: Padding, margin: number, width: number, height: number) {
  // Screen axes for this viewing direction (as three's lookAt builds them); project every box corner onto them.
  const forward = dir.clone().normalize();
  const right = new Vector3(0, 1, 0).cross(forward).normalize();
  const up = forward.clone().cross(right);
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const b of frames)
    for (const x of [b.min.x, b.max.x])
      for (const y of [b.min.y, b.max.y])
        for (const z of [b.min.z, b.max.z]) {
          const v = new Vector3(x, y, z);
          minX = Math.min(minX, v.dot(right));
          maxX = Math.max(maxX, v.dot(right));
          minY = Math.min(minY, v.dot(up));
          maxY = Math.max(maxY, v.dot(up));
        }
  const freeW = Math.max(100, width - padding.left - padding.right);
  const freeH = Math.max(100, height - padding.top - padding.bottom);
  const zoom = Math.min(freeW / (maxX - minX), freeH / (maxY - minY)) / margin;
  // Put the content's centre at the centre of the free area (screen y grows downward, `up` grows upward).
  const shiftX = (padding.left - padding.right) / 2;
  const shiftY = (padding.top - padding.bottom) / 2;
  const target = new Vector3()
    .addScaledVector(right, (minX + maxX) / 2 - shiftX / zoom)
    .addScaledVector(up, (minY + maxY) / 2 + shiftY / zoom)
    // keep the target's depth on the content, so orbiting pivots around the building
    .addScaledVector(forward, frames[0].getCenter(new Vector3()).dot(forward));
  return { target, zoom };
}

function focusBoxFor(placement: Placement, deviceId: string): Box3 | null {
  const p = placement.boxes.find((b) => b.meta.device.device_id === deviceId);
  if (!p) return null;
  const { x, y, w, d, h } = p.box;
  const pad = 2.8;
  return new Box3(new Vector3(x - pad, 0, y - pad), new Vector3(x + w + pad, h + 1.6, y + d + pad));
}

/** Presenter shortcuts in demo mode: Space play/pause, C +40 customers, S side by side, V view, L labels, F follow, Esc exit. */
function useDemoKeys(
  demo: boolean,
  on: { compare: () => void; follow: () => void; view: () => void; labels: () => void; exit: () => void },
) {
  const handlers = useRef(on);
  handlers.current = on;
  useEffect(() => {
    if (!demo) return;
    const onKey = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLElement &&
        e.target.closest("input, textarea, select, button, summary, [contenteditable=true], [role=dialog], [role=alertdialog]")
      )
        return;
      if (document.querySelector("[role=dialog], [role=alertdialog]")) return;
      const { clock } = useSim.getState();
      if (e.code === "Space") {
        e.preventDefault();
        transport.simControl({ action: clock?.playing ? "pause" : "play" }).catch(() => {});
      } else if (e.key === "c" || e.key === "C") {
        requestSurge(40).catch(() => {});
      } else if (e.key === "s" || e.key === "S") {
        handlers.current.compare();
      } else if (e.key === "v" || e.key === "V") {
        handlers.current.view();
      } else if (e.key === "l" || e.key === "L") {
        handlers.current.labels();
      } else if (e.key === "f" || e.key === "F") {
        handlers.current.follow();
      } else if (e.key === "Escape" && !document.querySelector("[role=dialog], [role=alertdialog]")) {
        handlers.current.exit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [demo]);
}
