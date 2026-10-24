import { forwardRef, useState } from "react";
import { Billboard, Edges, Html, Line, RoundedBox } from "@react-three/drei";
import { Color, DoubleSide, type Group } from "three";
import { ArrowDownToLine, Clock } from "lucide-react";
import type { DeviceMeta } from "@/hooks/useDeviceMeta";
import { fmtKw } from "@/lib/format";
import { DEVICE_STATE_LABEL } from "@/lib/theme";
import type { HubDeviceReading } from "@/types";
import {
  ACCENT,
  APPLIANCE,
  APPLIANCE_BY_CATEGORY,
  HELD_AMBER,
  INK,
  OFF_TINT,
  REDUCED_TEAL,
  RUNNING_LED,
  STATE_HEX,
} from "./palette";
import type { PlacedDevice } from "./plan";
import { Ink, Toon } from "./toon";

export type TagMode = "none" | "kw" | "action" | "status";

export interface DeviceProps {
  placed: PlacedDevice;
  reading?: HubDeviceReading;
  tag: TagMode;
  /** Pixels to lift the label so it doesn't overlap a neighbour's (a leader line fills the gap). */
  labelLift?: number;
  selected: boolean;
  interactive: boolean;
  onSelect: (id: string | null) => void;
}

/** Bright colors for things that should bloom (meshBasicMaterial with toneMapped off). */
const glow = (hex: string, k: number) => new Color(hex).multiplyScalar(Math.min(k, 2.5));
const OFF_GREY = OFF_TINT;

/** One piece of equipment: body, type details, status light, and glow that follows its live load. */
export const Device3D = forwardRef<Group, DeviceProps>(function Device3D(
  { placed, reading, tag, labelLift = 0, selected, interactive, onSelect },
  ref,
) {
  const { meta, box } = placed;
  const { w, d, h } = box;
  const type = meta.device.type_id;
  const state = reading?.state;
  const power = reading?.power_kw ?? 0;
  const running = state !== "off" && state !== "waiting" && power > 0;
  // Visual intensity only (never shown as a number): how hard the unit is working right now.
  const load = running && meta.device.rated_kw > 0 ? Math.min(1, power / meta.device.rated_kw) : 0;
  const accent = state === "reduced" ? REDUCED_TEAL : ACCENT[meta.category];
  const pastel = APPLIANCE[type] ?? APPLIANCE_BY_CATEGORY[meta.category];
  const [hovered, setHovered] = useState(false);
  const isRunning = state === "on" || state === "running_job";
  const isReduced = state === "reduced";
  const isWaiting = state === "waiting";
  // The body tells the operating state; intervention colours are reserved for reduced and held equipment.
  const statusColor = state ? STATE_HEX[state] : OFF_GREY;
  const bodyColor = state == null || state === "off"
    ? OFF_TINT
    : isWaiting
      ? new Color(pastel).lerp(new Color(OFF_TINT), 0.68).getStyle()
      : pastel;
  const outlineColor = isReduced ? REDUCED_TEAL : isWaiting ? HELD_AMBER : INK;
  const ledColor = isReduced ? REDUCED_TEAL : RUNNING_LED;

  return (
    <group
      ref={ref}
      position={[box.x + w / 2, box.z ?? 0, box.y + d / 2]}
      onClick={(e) => {
        if (!interactive) return;
        e.stopPropagation();
        onSelect(selected ? null : meta.device.device_id);
      }}
      onPointerOver={(e) => {
        if (!interactive) return;
        e.stopPropagation();
        setHovered(true);
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = "";
      }}
    >
      {type === "water_heater" ? (
        <mesh position={[0, h / 2, 0]} castShadow receiveShadow>
          <cylinderGeometry args={[Math.min(w, d) * 0.45, Math.min(w, d) * 0.45, h, 32]} />
          <Toon color={bodyColor} emissive={selected ? "#ffffff" : "#000000"} emissiveIntensity={selected ? 0.1 : 0} />
          <Ink color={outlineColor} thickness={isReduced || isWaiting ? 3.2 : 2.2} />
        </mesh>
      ) : (
        <RoundedBox args={[w, h, d]} radius={Math.min(0.07, w / 6, d / 6)} smoothness={3} position={[0, h / 2, 0]} castShadow receiveShadow>
          <Toon color={bodyColor} emissive={selected ? "#ffffff" : "#000000"} emissiveIntensity={selected ? 0.1 : 0} />
          <Ink color={outlineColor} thickness={isReduced || isWaiting ? 3.2 : 2.2} />
        </RoundedBox>
      )}

      <Details type={type} w={w} d={d} h={h} load={load} accent={accent} state={state ?? "unknown"} category={meta.category} />

      {(isRunning || isReduced) && <StatusLed position={[w / 2 - 0.13, h + 0.07, d / 2 - 0.13]} color={ledColor} />}
      {(isReduced || isWaiting) && (
        <StateRing radius={Math.max(w, d) * 0.72 + 0.25} color={statusColor} dashed={isWaiting} />
      )}
      {isWaiting && <ClockBadge position={[0, h + 0.55, 0]} />}

      {selected && (
        <mesh position={[0, h / 2, 0]}>
          <boxGeometry args={[w + 0.12, h + 0.12, d + 0.12]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
          <Edges color={INK} />
        </mesh>
      )}

      <Html position={[0, h + 0.3, 0]} zIndexRange={selected ? [60, 50] : [30, 10]} pointerEvents="none" style={{ transform: "translate(-50%, -100%)" }}>
        {/* Lifted clear of neighbouring labels (see useLabelOffsets), with a leader line back to the appliance. */}
        <div className="flex flex-col items-center">
          {selected || hovered ? (
            <HoverTag meta={meta} reading={reading} />
          ) : tag === "action" && reading ? (
            <ActionTag text={meta.device.name} kw={power} state={state ?? "unknown"} />
          ) : tag === "status" ? (
            <StatusTag name={meta.device.name} kw={power} state={state ?? "off"} />
          ) : tag === "kw" ? (
            <KwTag name={meta.device.name} kw={reading?.power_kw} color={state ? STATE_HEX[state] : "#64748b"} />
          ) : null}
          {tag !== "none" && !selected && !hovered && labelLift > 2 && (
            <div className="w-px" style={{ height: labelLift, background: `${statusColor}aa` }} />
          )}
        </div>
      </Html>
    </group>
  );
});

function Details({
  type,
  w,
  d,
  h,
  load,
  accent,
  state,
  category,
}: {
  type: string;
  w: number;
  d: number;
  h: number;
  load: number;
  accent: string;
  state: string;
  category: string;
}) {
  const front = d / 2 + 0.004;
  switch (type) {
    case "fryer":
      return (
        <>
          <mesh position={[0, h + 0.012, 0]} rotation-x={-Math.PI / 2}>
            <planeGeometry args={[w * 0.88, d * 0.72]} />
            <Toon color="#5B3A32" />
          </mesh>
          {[-w / 4, w / 4].map((x) => (
            <group key={x} position={[x, h + 0.035, -d * 0.03]}>
              <mesh rotation-x={-Math.PI / 2}>
                <planeGeometry args={[w * 0.32, d * 0.54]} />
                <meshBasicMaterial color={glow("#FF9F1C", 0.2 + load * 2.8)} toneMapped={false} />
              </mesh>
              <mesh position={[0, 0.055, 0]}>
                <boxGeometry args={[w * 0.34, 0.08, d * 0.56]} />
                <Toon color="#F4F1DE" wireframe />
              </mesh>
              <mesh position={[0, 0.24, d * 0.38]} rotation-x={-0.42}>
                <boxGeometry args={[0.055, 0.38, 0.055]} />
                <Toon color="#5F5A55" />
              </mesh>
            </group>
          ))}
        </>
      );
    case "grill":
      return (
        <>
          <mesh position={[0, h + 0.008, 0]} rotation-x={-Math.PI / 2}>
            <planeGeometry args={[w * 0.84, d * 0.72]} />
            <Toon color="#1c1f27" roughness={0.6} />
          </mesh>
          {[
            [-0.23, -0.2], [0.23, -0.2], [-0.23, 0.2], [0.23, 0.2],
          ].map(([x, z], i) => (
            <mesh key={i} position={[x * w, h + 0.024, z * d]} rotation-x={-Math.PI / 2}>
              <ringGeometry args={[Math.min(w, d) * 0.09, Math.min(w, d) * 0.145, 24]} />
              <meshBasicMaterial color={glow("#FF6B35", 0.15 + load * 3)} toneMapped={false} />
            </mesh>
          ))}
        </>
      );
    case "oven":
      return (
        <>
          <mesh position={[0, h * 0.86, front]}>
            <planeGeometry args={[w * 0.85, h * 0.1]} />
            <Toon color="#20242e" />
          </mesh>
          <mesh position={[0, h * 0.47, front]}>
            <planeGeometry args={[w * 0.7, h * 0.4]} />
            <meshBasicMaterial color={glow("#FF9F1C", 0.08 + load * 2.7)} toneMapped={false} />
          </mesh>
          <mesh position={[0, h * 0.72, front + 0.015]}>
            <boxGeometry args={[w * 0.58, 0.055, 0.055]} />
            <Toon color="#4A3F44" />
          </mesh>
        </>
      );
    case "dishwasher":
      return (
        <>
          <mesh position={[0, h * 0.47, front]}>
            <planeGeometry args={[w * 0.8, h * 0.76]} />
            <Toon color="#9aa1ad" metalness={0.6} roughness={0.35} />
          </mesh>
          <mesh position={[w * 0.32, h * 0.9, front + 0.001]}>
            <planeGeometry args={[0.12, 0.05]} />
            <meshBasicMaterial color={glow(state === "running_job" ? RUNNING_LED : "#8A817C", 2)} toneMapped={false} />
          </mesh>
          <mesh position={[0, h * 0.72, front + 0.025]}>
            <boxGeometry args={[w * 0.56, 0.055, 0.055]} />
            <Toon color="#4A5568" />
          </mesh>
        </>
      );
    case "walk_in_cooler":
    case "freezer":
      return (
        <>
          <mesh position={[w * 0.05, h * 0.43, d / 2 + 0.02]} castShadow>
            <boxGeometry args={[w * 0.42, h * 0.86, 0.04]} />
            <Toon color="#c3ccd7" metalness={0.2} roughness={0.45} />
          </mesh>
          <mesh position={[w * 0.21, h * 0.45, d / 2 + 0.05]}>
            <boxGeometry args={[0.04, h * 0.2, 0.04]} />
            <Toon color="#5b6475" metalness={0.6} />
          </mesh>
          <mesh position={[-w * 0.3, h * 0.78, front]}>
            <planeGeometry args={[0.32, 0.16]} />
            <meshBasicMaterial color={glow(accent, 0.6 + load * 2.4)} toneMapped={false} />
          </mesh>
        </>
      );
    case "reach_in_fridge":
      return (
        <>
          <mesh position={[0, h * 0.5, front]}>
            <planeGeometry args={[w * 0.84, h * 0.84]} />
            <meshBasicMaterial color={glow("#8ECAE6", 0.12 + load * 1.2)} transparent opacity={0.72} toneMapped={false} />
          </mesh>
          <mesh position={[0, h * 0.5, front + 0.012]}>
            <boxGeometry args={[0.035, h * 0.8, 0.025]} />
            <Toon color={INK} />
          </mesh>
          {[-0.1, 0.1].map((x) => (
            <mesh key={x} position={[x * w, h * 0.5, front + 0.035]}>
              <boxGeometry args={[0.035, h * 0.34, 0.035]} />
              <Toon color="#4A5568" />
            </mesh>
          ))}
        </>
      );
    case "ice_machine":
      return (
        <>
          <mesh position={[0, h * 0.32, front]}>
            <planeGeometry args={[w * 0.72, h * 0.4]} />
            <Toon color="#B7C9B2" />
          </mesh>
          <mesh position={[0, h * 0.55, front + 0.018]}>
            <boxGeometry args={[w * 0.5, 0.05, 0.04]} />
            <Toon color="#4A5568" />
          </mesh>
          <mesh position={[0, h * 0.78, front + 0.008]}>
            <boxGeometry args={[w * 0.22, h * 0.09, 0.03]} />
            <Toon color="#F4F1DE" />
          </mesh>
        </>
      );
    case "water_heater": {
      const r = Math.min(w, d) * 0.45;
      return (
        <mesh position={[0, h * 0.35, 0]}>
          <cylinderGeometry args={[r + 0.012, r + 0.012, 0.08, 32, 1, true]} />
          <meshBasicMaterial color={glow(accent, 0.2 + load * 3)} toneMapped={false} side={DoubleSide} />
        </mesh>
      );
    }
    default:
      return category === "cooling" ? <Fan w={w} d={d} h={h} /> : null;
  }
}

function Fan({ w, d, h }: { w: number; d: number; h: number }) {
  const r = Math.min(w, d) * 0.36;
  return (
    <group position={[0, h, 0]}>
      <mesh position={[0, 0.03, 0]}>
        <cylinderGeometry args={[r + 0.06, r + 0.06, 0.06, 32]} />
        <Toon color="#232834" roughness={0.6} />
      </mesh>
      <group position={[0, 0.07, 0]}>
        {[0, 1, 2, 3].map((i) => (
          <mesh key={i} rotation-y={(i * Math.PI) / 2}>
            <boxGeometry args={[r * 1.8, 0.015, 0.13]} />
            <Toon color="#b9c3cf" metalness={0.5} roughness={0.35} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

function StatusLed({ position, color }: { position: [number, number, number]; color: string }) {
  return (
    <mesh position={position}>
      <sphereGeometry args={[0.075, 16, 12]} />
      <meshBasicMaterial color={glow(color, 2.2)} toneMapped={false} />
    </mesh>
  );
}

/** Reduced is a solid teal ring; held is the same calm geometry with an amber dash pattern. */
function StateRing({ radius, color, dashed }: { radius: number; color: string; dashed: boolean }) {
  const points = Array.from({ length: 65 }, (_, i) => {
    const angle = (i / 64) * Math.PI * 2;
    return [Math.cos(angle) * radius, 0.035, Math.sin(angle) * radius] as [number, number, number];
  });
  return (
    <Line points={points} color={color} lineWidth={3} transparent opacity={0.9} dashed={dashed} dashSize={0.18} gapSize={0.12} />
  );
}

function ClockBadge({ position }: { position: [number, number, number] }) {
  return (
    <Billboard position={position}>
      <mesh>
        <circleGeometry args={[0.22, 32]} />
        <meshBasicMaterial color="#ffffff" toneMapped={false} />
        <Ink thickness={2} />
      </mesh>
      <mesh position={[0, 0.035, 0.002]} rotation-z={-0.7}>
        <boxGeometry args={[0.025, 0.13, 0.02]} />
        <meshBasicMaterial color={INK} />
      </mesh>
      <mesh position={[0.045, -0.015, 0.003]} rotation-z={0.65}>
        <boxGeometry args={[0.02, 0.1, 0.02]} />
        <meshBasicMaterial color={INK} />
      </mesh>
    </Billboard>
  );
}

// ---------- labels (DOM, so they stay crisp at any zoom) ----------

function KwTag({ name, kw, color }: { name: string; kw?: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-[#0f1424]/85 px-2 py-0.5 text-[11px] whitespace-nowrap shadow-lg backdrop-blur-sm">
      <span className="size-1.5 rounded-full" style={{ background: color }} />
      <span className="text-white/70">{name}</span>
      <span className="font-semibold text-white tabular-nums">{fmtKw(kw)}</span>
    </div>
  );
}

/** Always-on label for a working appliance: status colour, name and live kW. */
function StatusTag({ name, kw, state }: { name: string; kw: number; state: string }) {
  const color = STATE_HEX[state as keyof typeof STATE_HEX] ?? OFF_GREY;
  return (
    <div
      className="flex items-center gap-1.5 rounded-md border bg-[#0b1020]/90 px-2 py-1 text-xs whitespace-nowrap shadow-lg"
      style={{ borderColor: `${color}99` }}
    >
      <span className="size-2 rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
      <span className="font-medium text-white">{name}</span>
      <span className="font-semibold tabular-nums" style={{ color }}>
        {fmtKw(kw)}
      </span>
    </div>
  );
}

function ActionTag({ text, kw, state }: { text: string; kw: number; state: string }) {
  const reduced = state === "reduced";
  const Icon = reduced ? ArrowDownToLine : Clock;
  return (
    <div
      className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium whitespace-nowrap shadow-lg backdrop-blur-sm"
      style={{
        color: reduced ? STATE_HEX.reduced : STATE_HEX.waiting,
        borderColor: `${reduced ? STATE_HEX.reduced : STATE_HEX.waiting}66`,
        background: "rgba(15,20,36,0.88)",
      }}
    >
      <Icon className="size-3.5" />
      {text} · {reduced ? "Reduced" : "Waiting"}
      {reduced && <span className="text-white/80 tabular-nums">· {fmtKw(kw)}</span>}
    </div>
  );
}

function HoverTag({ meta, reading }: { meta: DeviceMeta; reading?: HubDeviceReading }) {
  const state = reading?.state;
  const Icon = meta.icon;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-white/15 bg-[#0f1424]/95 px-2.5 py-1.5 whitespace-nowrap shadow-xl">
      <span
        className="flex size-6 items-center justify-center rounded-md"
        style={{ background: `color-mix(in oklch, ${meta.color} 22%, transparent)`, color: meta.color }}
      >
        <Icon className="size-3.5" />
      </span>
      <div className="leading-tight">
        <div className="text-xs font-medium text-white">{meta.device.name}</div>
        <div className="text-[11px] text-white/60">
          <span className="font-semibold text-white tabular-nums">{fmtKw(reading?.power_kw)}</span> ·{" "}
          <span style={{ color: state ? STATE_HEX[state] : "#64748b" }}>{state ? DEVICE_STATE_LABEL[state] : "No reading"}</span> · select
          in appliance list
        </div>
      </div>
    </div>
  );
}
