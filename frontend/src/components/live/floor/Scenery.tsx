import { memo, useMemo } from "react";
import { Html } from "@react-three/drei";
import { Furniture } from "./Furniture";
import { INNER_WALL, PROP, WALL } from "./palette";
import { BACK_WALLS, PROPS, ROOMS, WALLS, WINDOWS, type Box, type FloorKind } from "./plan";
import { texture, type TextureKind } from "./textures";

/** Floor finish per room: [texture, metres per texture tile, roughness]. */
const FINISH: Record<FloorKind, [TextureKind, number, number]> = {
  kitchen: ["tile", 1, 0.55],
  dish: ["tile", 1, 0.55],
  cold: ["coldTile", 2, 0.5],
  office: ["carpet", 2, 1],
  dining: ["planks", 3, 0.6],
  pad: ["concrete", 2, 0.95],
};

/** three.js position of a plan box (centre of the box). */
export const boxPosition = (b: Box): [number, number, number] => [b.x + b.w / 2, (b.z ?? 0) + b.h / 2, b.y + b.d / 2];
export const boxArgs = (b: Box): [number, number, number] => [b.w, b.h, b.d];

/**
 * Floors, walls, windows and furniture. With `focus` on, furniture is hidden and floors are darkened so the
 * appliances are the only objects on the floor.
 */
export const Scenery = memo(function Scenery({ roomLabels, focus }: { roomLabels: boolean; focus: boolean }) {
  const floors = useMemo(
    () =>
      ROOMS.map((r) => {
        const [kind, tileM, rough] = FINISH[r.kind];
        return { room: r, map: texture(kind, r.w / tileM, r.d / tileM), rough };
      }),
    [],
  );
  return (
    <group>
      {floors.map(({ room: r, map, rough }, i) => (
        <mesh key={i} position={[r.x + r.w / 2, 0, r.y + r.d / 2]} rotation-x={-Math.PI / 2} receiveShadow>
          <planeGeometry args={[r.w, r.d]} />
          {/* `color` multiplies the texture: darker floors in focus mode */}
          <meshStandardMaterial map={map} color={focus ? "#4b5563" : "#ffffff"} roughness={rough} metalness={0.02} />
        </mesh>
      ))}

      {BACK_WALLS.map((b, i) => (
        <mesh key={i} position={boxPosition(b)} castShadow receiveShadow>
          <boxGeometry args={boxArgs(b)} />
          <meshStandardMaterial color={WALL} roughness={0.9} />
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
              <meshStandardMaterial color="#132447" emissive="#3d6fd1" emissiveIntensity={0.08} roughness={0.15} />
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
                <meshStandardMaterial color="#d8dce4" roughness={0.5} />
              </mesh>
            ))}
          </group>
        );
      })}
      {WALLS.map((b, i) => (
        <mesh key={i} position={boxPosition(b)} castShadow receiveShadow>
          <boxGeometry args={boxArgs(b)} />
          <meshStandardMaterial color={INNER_WALL} roughness={0.85} />
        </mesh>
      ))}

      {!focus &&
        PROPS.map((p, i) => {
          const m = PROP[p.kind];
          return (
            <mesh key={i} position={boxPosition(p.box)} castShadow receiveShadow>
              <boxGeometry args={boxArgs(p.box)} />
              <meshStandardMaterial color={m.color} metalness={m.metal ?? 0} roughness={m.rough ?? 0.8} flatShading={p.kind === "leaves"} />
            </mesh>
          );
        })}
      {!focus && <Furniture />}

      {roomLabels &&
        ROOMS.filter((r) => r.label).map((r) => (
          <Html key={r.label} position={[r.x + 0.3, 0.02, r.y + r.d - 0.3]} zIndexRange={[5, 0]} pointerEvents="none">
            <div className="text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-white/35 uppercase">{r.label}</div>
          </Html>
        ))}
    </group>
  );
});
