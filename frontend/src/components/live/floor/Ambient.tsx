import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html, Line, RoundedBox } from "@react-three/drei";
import { Color, DoubleSide, Object3D, type Group, type InstancedMesh } from "three";
import type { Line2 } from "three-stdlib";
import { Cpu } from "lucide-react";
import { fmtKw } from "@/lib/format";
import type { Lane, Meter } from "@/types";
import { LANE_HEX, SHIRTS, SKIN } from "./palette";
import { FOOTPRINT, HUB_BOX, HUB_FLOOR, SEATS, TABLES, type Pt, type Seat } from "./plan";

const glow = (hex: string, k: number) => new Color(hex).multiplyScalar(k);

// ---------- energy flowing to the hub ----------

export interface FlowRoute {
  id: string;
  points: Pt[];
  kw: number;
  active: boolean;
}

const PER_ROUTE = 6;

/** Each device's cable to the hub, with particles whose speed follows its live kW ("motion that explains"). */
export function EnergyFlow({ routes, lane }: { routes: FlowRoute[]; lane: Lane }) {
  const mesh = useRef<InstancedMesh>(null);
  const dummy = useMemo(() => new Object3D(), []);
  const color = useMemo(() => glow(LANE_HEX[lane], 2.6), [lane]);
  const lengths = useMemo(
    () =>
      routes.map((r) => {
        const segs = r.points.slice(1).map((p, i) => Math.hypot(p[0] - r.points[i][0], p[1] - r.points[i][1]));
        return { segs, total: segs.reduce((a, b) => a + b, 0) };
      }),
    [routes],
  );

  useFrame(({ clock }) => {
    const m = mesh.current;
    if (!m) return;
    const t = clock.elapsedTime;
    routes.forEach((r, ri) => {
      const { segs, total } = lengths[ri];
      const speed = 1.4 + 0.7 * Math.sqrt(r.kw); // visual only
      for (let k = 0; k < PER_ROUTE; k++) {
        if (!r.active || total === 0) {
          dummy.scale.setScalar(0);
        } else {
          let dist = (((t * speed) / total + k / PER_ROUTE) % 1) * total;
          let s = 0;
          while (s < segs.length - 1 && dist > segs[s]) dist -= segs[s++];
          const [ax, ay] = r.points[s];
          const [bx, by] = r.points[s + 1];
          const f = segs[s] ? dist / segs[s] : 0;
          dummy.position.set(ax + (bx - ax) * f, 0.07, ay + (by - ay) * f);
          dummy.scale.setScalar(1);
        }
        dummy.updateMatrix();
        m.setMatrixAt(ri * PER_ROUTE + k, dummy.matrix);
      }
    });
    m.instanceMatrix.needsUpdate = true;
  });

  return (
    <group>
      {routes.map((r) => (
        <Line
          key={r.id}
          points={r.points.map(([x, y]) => [x, 0.025, y] as [number, number, number])}
          color={LANE_HEX[lane]}
          lineWidth={1.2}
          transparent
          opacity={r.active ? 0.3 : 0.07}
        />
      ))}
      <instancedMesh
        key={routes.length}
        ref={mesh}
        args={[undefined, undefined, Math.max(1, routes.length * PER_ROUTE)]}
        frustumCulled={false}
      >
        <sphereGeometry args={[0.075, 10, 8]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

// ---------- the hub ----------

/** The simulated ESP32 every device reports to. A ring pulses out on every tick it receives. */
export function Hub3D({ totalKw, deviceCount, showLabel }: { totalKw?: number; deviceCount: number; showLabel: boolean }) {
  const { x, y, z = 0, w, d, h } = HUB_BOX;
  const top = z + h;
  return (
    <group>
      <RoundedBox args={[w, h, d]} radius={0.05} position={[x + w / 2, z + h / 2, y + d / 2]} castShadow>
        <meshStandardMaterial color="#232a3b" metalness={0.4} roughness={0.4} />
      </RoundedBox>
      <mesh position={[x + w / 2, top + 0.005, y + d / 2]} rotation-x={-Math.PI / 2}>
        <planeGeometry args={[w * 0.8, 0.05]} />
        <meshBasicMaterial color={glow(LANE_HEX.with, 3)} toneMapped={false} />
      </mesh>
      <mesh position={[x + 0.15, top + 0.35, y + 0.15]}>
        <cylinderGeometry args={[0.015, 0.015, 0.7, 8]} />
        <meshStandardMaterial color="#9aa3b2" metalness={0.6} />
      </mesh>
      <mesh position={[x + 0.15, top + 0.72, y + 0.15]}>
        <sphereGeometry args={[0.05, 12, 10]} />
        <meshBasicMaterial color={glow(LANE_HEX.with, 3.5)} toneMapped={false} />
      </mesh>
      {/* Where the cables arrive */}
      <mesh position={[HUB_FLOOR[0], 0.02, HUB_FLOOR[1]]} rotation-x={-Math.PI / 2}>
        <circleGeometry args={[0.22, 24]} />
        <meshBasicMaterial color={glow(LANE_HEX.with, 1.6)} toneMapped={false} />
      </mesh>
      {showLabel && (
        <Html
          position={[x + w / 2, 0, y + d + 1.2]}
          zIndexRange={[30, 10]}
          pointerEvents="none"
          style={{ transform: "translate(-50%, 0)" }}
        >
          <div className="flex items-center gap-2 rounded-lg border border-emerald-400/40 bg-[#0f1424]/90 px-2.5 py-1.5 whitespace-nowrap shadow-xl">
            <span className="flex size-6 items-center justify-center rounded-md bg-emerald-400/20 text-emerald-300">
              <Cpu className="size-3.5" />
            </span>
            <div className="leading-tight">
              <div className="text-[10px] text-white/60">Hub · simulated ESP32 · {deviceCount} devices</div>
              <div className="text-sm font-semibold text-white tabular-nums">{fmtKw(totalKw)}</div>
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}

// ---------- diners ----------

export function Diners({ occupied }: { occupied: Set<number> }) {
  return (
    <group>
      {SEATS.map((seat, i) => (
        <Diner key={i} seat={seat} index={i} visible={occupied.has(i)} />
      ))}
    </group>
  );
}

const HAIR = ["#2b1d14", "#4a2f1d", "#c9a35e", "#111111", "#7a4a2a"];
const PANTS = ["#2a3142", "#3b3f4a", "#1f2633", "#4a3b2f"];

/** A seated diner facing the table (+z in the seat's frame). Grows in or out as customers come and go. */
function Diner({ seat, index, visible }: { seat: Seat; index: number; visible: boolean }) {
  const g = useRef<Group>(null);
  useFrame((_, dt) => {
    const m = g.current;
    if (!m) return;
    const next = m.scale.x + ((visible ? 1 : 0) - m.scale.x) * Math.min(1, dt * 3.5);
    m.scale.setScalar(Math.max(0.0001, next));
    m.visible = next > 0.02;
  });
  const shirt = SHIRTS[index % SHIRTS.length];
  return (
    <group ref={g} position={[seat.at[0], 0, seat.at[1]]} rotation-y={seat.rot} scale={0.0001}>
      {/* thighs on the seat, shins down */}
      <mesh position={[0, 0.54, 0.1]} castShadow>
        <boxGeometry args={[0.3, 0.12, 0.34]} />
        <meshStandardMaterial color={PANTS[index % PANTS.length]} roughness={0.85} />
      </mesh>
      <mesh position={[0, 0.27, 0.25]} castShadow>
        <boxGeometry args={[0.26, 0.5, 0.1]} />
        <meshStandardMaterial color={PANTS[index % PANTS.length]} roughness={0.85} />
      </mesh>
      {/* torso, leaning slightly toward the table */}
      <mesh position={[0, 0.84, -0.06]} rotation-x={0.12} castShadow>
        <capsuleGeometry args={[0.14, 0.24, 4, 12]} />
        <meshStandardMaterial color={shirt} roughness={0.8} />
      </mesh>
      {/* arms resting toward the table */}
      {[-0.18, 0.18].map((x) => (
        <mesh key={x} position={[x, 0.86, 0.08]} rotation-x={-1.05} castShadow>
          <capsuleGeometry args={[0.045, 0.24, 4, 8]} />
          <meshStandardMaterial color={shirt} roughness={0.8} />
        </mesh>
      ))}
      <mesh position={[0, 1.2, -0.03]} castShadow>
        <sphereGeometry args={[0.11, 16, 12]} />
        <meshStandardMaterial color={SKIN[index % SKIN.length]} roughness={0.7} />
      </mesh>
      <mesh position={[0, 1.24, -0.06]} castShadow>
        <sphereGeometry args={[0.115, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color={HAIR[index % HAIR.length]} roughness={0.9} />
      </mesh>
    </group>
  );
}

// ---------- pendant lamps (the lights device) ----------

/**
 * Pendant lamps over the tables; `level` (0–1) dims them with the lights unit's live power. Light in the air and on
 * the table is faked with additive cones and pools (a few real lights in Restaurant carry the warmth).
 */
export function Lamps({ tables, level }: { tables: number[]; level: number }) {
  return (
    <group>
      {tables.map((t) => {
        const [tx, ty] = TABLES[t];
        const cx = tx + 0.5;
        const cz = ty + 0.5;
        return (
          <group key={t} position={[cx, 0, cz]}>
            <mesh position={[0, 2.95, 0]}>
              <cylinderGeometry args={[0.008, 0.008, 0.75, 6]} />
              <meshStandardMaterial color="#2a2f3a" />
            </mesh>
            <mesh position={[0, 2.5, 0]}>
              <coneGeometry args={[0.24, 0.2, 24, 1, true]} />
              <meshStandardMaterial color="#b8894a" metalness={0.6} roughness={0.35} side={DoubleSide} />
            </mesh>
            <mesh position={[0, 2.41, 0]}>
              <sphereGeometry args={[0.07, 12, 10]} />
              <meshBasicMaterial color={glow("#ffcf8a", 0.3 + level * 0.6)} toneMapped={false} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

// ---------- the cap outline ----------

/** Outline around the building: green while the 15-minute average is under the cap, pulsing red when it's over. */
export function CapOutline({ meter, showLabel }: { meter?: Meter; showLabel: boolean }) {
  const line = useRef<Line2>(null);
  const over = meter != null && meter.block_avg_kw > meter.peak_cap_kw;
  useFrame(({ clock }) => {
    if (line.current) line.current.material.opacity = over ? 0.55 + 0.45 * Math.sin(clock.elapsedTime * 6) : 0.5;
  });
  const m = 0.35;
  const { x, y, w, d } = FOOTPRINT;
  const pts: [number, number, number][] = [
    [x - m, 0.04, y - m],
    [x + w + m, 0.04, y - m],
    [x + w + m, 0.04, y + d + m],
    [x - m, 0.04, y + d + m],
    [x - m, 0.04, y - m],
  ];
  return (
    <group>
      <Line ref={line} points={pts} color={over ? "#ff5a5a" : LANE_HEX.with} lineWidth={over ? 3.5 : 2} transparent />
      {showLabel && meter && (
        <Html
          position={[x + w * 0.42, 0.05, y + d + m + 0.3]}
          zIndexRange={[30, 10]}
          pointerEvents="none"
          style={{ transform: "translate(-50%, 0)" }}
        >
          <div
            className={
              over
                ? "animate-pulse rounded-full border border-red-400/60 bg-red-500/20 px-3 py-1 text-xs font-semibold whitespace-nowrap text-red-200 shadow-lg"
                : "rounded-full border border-emerald-400/40 bg-emerald-500/10 px-3 py-1 text-xs font-medium whitespace-nowrap text-emerald-200 shadow-lg"
            }
          >
            {over ? "Over the cap" : "Under the cap"} · 15-min avg {fmtKw(meter.block_avg_kw)} / cap {fmtKw(meter.peak_cap_kw)}
          </div>
        </Html>
      )}
    </group>
  );
}

/** Big lane name above a restaurant in side-by-side mode. */
export function LaneTitle({ lane }: { lane: Lane }) {
  return (
    <Html
      position={[FOOTPRINT.w / 2, 3.4, -0.4]}
      zIndexRange={[30, 10]}
      pointerEvents="none"
      style={{ transform: "translate(-50%, -100%)" }}
    >
      <div
        className="rounded-full border px-4 py-1.5 text-sm font-semibold whitespace-nowrap shadow-xl backdrop-blur-sm"
        style={{ color: LANE_HEX[lane], borderColor: `${LANE_HEX[lane]}66`, background: "rgba(15,20,36,0.85)" }}
      >
        {lane === "with" ? "With WattWise" : "Without WattWise"}
      </div>
    </Html>
  );
}
