import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import type { Group } from "three";
import type { Pt } from "./plan";

// Kitchen and floor staff, animated purely for life on the floor (no data behind them).

const CHEF_STATIONS: Pt[] = [
  [1.5, 2.15],
  [3.8, 2.15],
  [6.1, 2.15],
  [8.4, 2.15],
];

/** Waiters walk these aisles from the pass and back (ping-pong along the route). */
const WAITER_ROUTES: Pt[][] = [
  [
    [7.5, 7.75],
    [7.65, 10.4],
    [9.95, 10.4],
    [9.95, 9.25],
    [19.9, 9.25],
  ],
  [
    [7.5, 7.75],
    [7.65, 10.4],
    [9.95, 10.4],
    [9.95, 12.55],
    [19.5, 12.55],
  ],
  [
    [7.5, 7.75],
    [7.65, 10.4],
    [5.4, 10.4],
  ],
];
const WALK_SPEED = 1.25; // m/s

export function Staff({ busy }: { busy: boolean }) {
  return (
    <group>
      <Chef offset={0} />
      <Chef offset={2.7} />
      <Waiter route={WAITER_ROUTES[0]} phase={0} />
      <Waiter route={WAITER_ROUTES[1]} phase={0.45} />
      {busy && <Waiter route={WAITER_ROUTES[2]} phase={0.2} />}
    </group>
  );
}

function Chef({ offset }: { offset: number }) {
  const g = useRef<Group>(null);
  useFrame(({ clock }, dt) => {
    const m = g.current;
    if (!m) return;
    const t = clock.elapsedTime + offset;
    const [tx, tz] = CHEF_STATIONS[Math.floor(t / 4.5 + offset) % CHEF_STATIONS.length];
    const dx = tx - m.position.x;
    const dz = tz - m.position.z;
    const dist = Math.hypot(dx, dz);
    if (dist > 0.05) {
      const step = Math.min(dist, dt * WALK_SPEED);
      m.position.x += (dx / dist) * step;
      m.position.z += (dz / dist) * step;
      m.rotation.y = Math.atan2(dx, dz);
      m.position.y = Math.abs(Math.sin(t * 9)) * 0.03;
    } else {
      m.rotation.y += (Math.PI - m.rotation.y) * Math.min(1, dt * 5); // face the cook line
      m.position.y = 0;
    }
  });
  const start = CHEF_STATIONS[Math.round(offset) % CHEF_STATIONS.length];
  return (
    <group ref={g} position={[start[0], 0, start[1]]}>
      <Person shirt="#f4f4f2" pants="#3a3d45" skin="#e6b896" />
      {/* toque */}
      <mesh position={[0, 1.78, 0]} castShadow>
        <cylinderGeometry args={[0.1, 0.1, 0.16, 16]} />
        <meshStandardMaterial color="#ffffff" roughness={0.6} />
      </mesh>
      <mesh position={[0, 1.88, 0]} castShadow>
        <sphereGeometry args={[0.14, 16, 10]} />
        <meshStandardMaterial color="#ffffff" roughness={0.6} />
      </mesh>
    </group>
  );
}

function Waiter({ route, phase }: { route: Pt[]; phase: number }) {
  const g = useRef<Group>(null);
  const { segs, total } = useMemo(() => {
    const segs = route.slice(1).map((p, i) => Math.hypot(p[0] - route[i][0], p[1] - route[i][1]));
    return { segs, total: segs.reduce((a, b) => a + b, 0) };
  }, [route]);

  useFrame(({ clock }) => {
    const m = g.current;
    if (!m) return;
    const t = clock.elapsedTime;
    // Ping-pong along the route, pausing briefly at each end (at the pass and at a table).
    const cycle = (2 * total) / WALK_SPEED + 3;
    let u = (((t / cycle + phase) % 1) + 1) % 1;
    const walkFrac = ((2 * total) / WALK_SPEED) / cycle;
    let dir = 1;
    let d: number;
    if (u < walkFrac / 2) d = (u / (walkFrac / 2)) * total;
    else if (u < walkFrac / 2 + (1 - walkFrac) / 2) d = total;
    else if (u < walkFrac + (1 - walkFrac) / 2) {
      u -= walkFrac / 2 + (1 - walkFrac) / 2;
      d = total - (u / (walkFrac / 2)) * total;
      dir = -1;
    } else d = 0;
    let s = 0;
    while (s < segs.length - 1 && d > segs[s]) d -= segs[s++];
    const [ax, az] = route[s];
    const [bx, bz] = route[s + 1];
    const f = segs[s] ? Math.min(1, d / segs[s]) : 0;
    m.position.set(ax + (bx - ax) * f, 0, az + (bz - az) * f);
    const moving = d > 0.01 && d < segs[s] - 0.01;
    if (moving) {
      m.rotation.y = Math.atan2((bx - ax) * dir, (bz - az) * dir);
      m.position.y = Math.abs(Math.sin(t * 9)) * 0.03;
    }
  });

  return (
    <group ref={g}>
      <Person shirt="#ffffff" pants="#16181d" skin="#c98e63" vest="#16181d" />
      {/* tray held up on the right */}
      <mesh position={[0.24, 1.32, 0.1]} castShadow>
        <cylinderGeometry args={[0.19, 0.19, 0.02, 20]} />
        <meshStandardMaterial color="#b8bec8" metalness={0.7} roughness={0.3} />
      </mesh>
      <mesh position={[0.2, 1.37, 0.12]} castShadow>
        <cylinderGeometry args={[0.03, 0.025, 0.09, 10]} />
        <meshStandardMaterial color="#cfe6ff" roughness={0.1} transparent opacity={0.7} />
      </mesh>
    </group>
  );
}

/** A standing figure facing +z. */
function Person({ shirt, pants, skin, vest }: { shirt: string; pants: string; skin: string; vest?: string }) {
  return (
    <group>
      {[-0.08, 0.08].map((x) => (
        <mesh key={x} position={[x, 0.4, 0]} castShadow>
          <boxGeometry args={[0.12, 0.8, 0.14]} />
          <meshStandardMaterial color={pants} roughness={0.85} />
        </mesh>
      ))}
      <mesh position={[0, 1.08, 0]} castShadow>
        <capsuleGeometry args={[0.16, 0.36, 4, 12]} />
        <meshStandardMaterial color={vest ?? shirt} roughness={0.8} />
      </mesh>
      {vest && (
        <mesh position={[0, 1.2, 0.12]}>
          <boxGeometry args={[0.12, 0.26, 0.06]} />
          <meshStandardMaterial color={shirt} roughness={0.8} />
        </mesh>
      )}
      {[-0.22, 0.22].map((x) => (
        <mesh key={x} position={[x, 1.08, 0.02]} castShadow>
          <capsuleGeometry args={[0.05, 0.4, 4, 8]} />
          <meshStandardMaterial color={shirt} roughness={0.8} />
        </mesh>
      ))}
      <mesh position={[0, 1.53, 0]} castShadow>
        <sphereGeometry args={[0.12, 16, 12]} />
        <meshStandardMaterial color={skin} roughness={0.7} />
      </mesh>
    </group>
  );
}
