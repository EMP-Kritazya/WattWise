import { memo, useMemo } from "react";
import { Html } from "@react-three/drei";
import { Furniture } from "./Furniture";
import { FLOOR, INK, INNER_WALL, PROP, WALL, WINDOW } from "./palette";
import { BACK_WALLS, PROPS, ROOMS, WALLS, WINDOWS, type Box } from "./plan";
import { Ink, Toon, floorPattern } from "./toon";

/** three.js position of a plan box (centre of the box). */
export const boxPosition = (b: Box): [number, number, number] => [b.x + b.w / 2, (b.z ?? 0) + b.h / 2, b.y + b.d / 2];
export const boxArgs = (b: Box): [number, number, number] => [b.w, b.h, b.d];

/**
 * Floors, walls, windows and furniture in the Toy Box style. With `focus` on, furniture is hidden so the appliances
 * are the only objects on the floor.
 */
export const Scenery = memo(function Scenery({ roomLabels, focus }: { roomLabels: boolean; focus: boolean }) {
  const floors = useMemo(
    () =>
      ROOMS.map((r) => {
        const [kind, a, b] = FLOOR[r.kind];
        // One pattern repeat covers 2 m: four 1 m checker tiles, or four 0.5 m planks.
        return { room: r, map: floorPattern(kind, a, b, r.w / 2, r.d / 2) };
      }),
    [],
  );
  return (
    <group>
      {floors.map(({ room: r, map }, i) => (
        <mesh key={i} position={[r.x + r.w / 2, 0, r.y + r.d / 2]} rotation-x={-Math.PI / 2} receiveShadow>
          <planeGeometry args={[r.w, r.d]} />
          {/* Focus mode only hides furniture; the floors stay light so the pastel appliances read against them. */}
          <Toon map={map} color={focus ? "#f4efe8" : "#ffffff"} />
        </mesh>
      ))}

      {BACK_WALLS.map((b, i) => (
        <mesh key={i} position={boxPosition(b)} castShadow receiveShadow>
          <boxGeometry args={boxArgs(b)} />
          <Toon color={WALL} />
          <Ink />
        </mesh>
      ))}
      {WINDOWS.map((w, i) => {
        const mid = (w.from + w.to) / 2;
        const zMid = (w.z0 + w.z1) / 2;
        const len = w.to - w.from;
        const tall = w.z1 - w.z0;
        return (
          // Night-time window: glowing glass, a frame and a centre mullion.
          <group key={i} position={w.wall === "x" ? [mid, zMid, 0.012] : [0.012, zMid, mid]} rotation-y={w.wall === "x" ? 0 : Math.PI / 2}>
            <mesh>
              <planeGeometry args={[len, tall]} />
              <Toon color={WINDOW} />
            </mesh>
            {[
              [0, tall / 2, len + 0.1, 0.07],
              [0, -tall / 2, len + 0.14, 0.09],
              [-len / 2, 0, 0.07, tall],
              [len / 2, 0, 0.07, tall],
              [0, 0, 0.05, tall],
            ].map(([x, y, fw, fh], k) => (
              <mesh key={k} position={[x, y, 0.03]}>
                <boxGeometry args={[fw, fh, 0.06]} />
                <Toon color="#FFFFFF" />
              </mesh>
            ))}
          </group>
        );
      })}
      {WALLS.map((b, i) => (
        <mesh key={i} position={boxPosition(b)} castShadow receiveShadow>
          <boxGeometry args={boxArgs(b)} />
          <Toon color={INNER_WALL} />
          <Ink thickness={1.6} />
        </mesh>
      ))}

      {!focus &&
        PROPS.map((p, i) => {
          const m = PROP[p.kind];
          return (
            <mesh key={i} position={boxPosition(p.box)} castShadow receiveShadow>
              <boxGeometry args={boxArgs(p.box)} />
              <Toon color={m.color} />
              <Ink thickness={1.6} />
            </mesh>
          );
        })}
      {!focus && <Furniture />}

      {roomLabels &&
        ROOMS.filter((r) => r.label).map((r) => (
          <Html key={r.label} position={[r.x + 0.3, 0.02, r.y + r.d - 0.3]} zIndexRange={[5, 0]} pointerEvents="none">
            <div className="text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap uppercase" style={{ color: INK, opacity: 0.4 }}>{r.label}</div>
          </Html>
        ))}
    </group>
  );
});
