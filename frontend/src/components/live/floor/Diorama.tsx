import { memo, useMemo } from "react";
import { Color } from "three";
import { LightCone, LightPool } from "./Effects3D";
import { texture } from "./textures";

// The ground the restaurant stands on: a cut-away slab of earth with a sidewalk, trees and street lamps,
// like an architectural diorama. Plan coordinates as in plan.ts (x along the back wall, y toward the camera).

export const BASE = { x0: -1.2, x1: 25.4, y0: -1.2, y1: 16.2 };
const SLAB_DEPTH = 0.75;

const TREES: [number, number, number][] = [
  [2.6, 14.4, 1],
  [10.2, 14.5, 1.15],
  [16.8, 14.4, 0.95],
  [24.2, 1.6, 1.2],
  [23.4, 14.3, 1.05],
];
const LAMPS: [number, number][] = [
  [6.4, 14.9],
  [13.5, 14.9],
  [20.4, 14.9],
];

const glow = (hex: string, k: number) => new Color(hex).multiplyScalar(k);

export const Diorama = memo(function Diorama() {
  const sidewalk = useMemo(() => texture("concrete", (BASE.x1 - BASE.x0) / 2, (BASE.y1 - 13.1) / 2), []);
  const yard = useMemo(() => texture("grass", 4, 6), []);
  const strip = useMemo(() => texture("grass", 12, 1), []);
  const w = BASE.x1 - BASE.x0;
  const d = BASE.y1 - BASE.y0;

  return (
    <group>
      {/* Earth slab with a concrete top layer */}
      <mesh position={[BASE.x0 + w / 2, -SLAB_DEPTH / 2 - 0.12, BASE.y0 + d / 2]} receiveShadow>
        <boxGeometry args={[w, SLAB_DEPTH, d]} />
        <meshStandardMaterial color="#3b2a1e" roughness={1} />
      </mesh>
      {/* top stays 1 cm below the room floors so they never z-fight */}
      <mesh position={[BASE.x0 + w / 2, -0.075, BASE.y0 + d / 2]} receiveShadow>
        <boxGeometry args={[w, 0.13, d]} />
        <meshStandardMaterial color="#5c6270" roughness={0.95} />
      </mesh>

      {/* Sidewalk along the front */}
      <mesh position={[BASE.x0 + w / 2, 0.006, (13.1 + BASE.y1) / 2]} rotation-x={-Math.PI / 2} receiveShadow>
        <planeGeometry args={[w, BASE.y1 - 13.1]} />
        <meshStandardMaterial map={sidewalk} roughness={0.95} />
      </mesh>
      {/* Grass: the side yard behind the roof units and a verge along the back */}
      <mesh position={[23.1, 0.007, 2.1]} rotation-x={-Math.PI / 2} receiveShadow>
        <planeGeometry args={[4.2, 6.6]} />
        <meshStandardMaterial map={yard} roughness={1} />
      </mesh>
      <mesh position={[BASE.x0 + w / 2, 0.007, -0.7]} rotation-x={-Math.PI / 2} receiveShadow>
        <planeGeometry args={[w, 1]} />
        <meshStandardMaterial map={strip} roughness={1} />
      </mesh>

      {/* Fence around the roof-unit yard */}
      {[
        [21.6, 5.2, 25.0, 5.2],
        [25.0, 5.2, 25.0, 12.9],
        [21.6, 12.9, 25.0, 12.9],
      ].map(([ax, ay, bx, by], i) => {
        const len = Math.hypot(bx - ax, by - ay);
        const along = ax === bx ? "y" : "x";
        return (
          <group key={i}>
            {[0.35, 0.75].map((h) => (
              <mesh key={h} position={[(ax + bx) / 2, h, (ay + by) / 2]} castShadow>
                <boxGeometry args={along === "x" ? [len, 0.04, 0.04] : [0.04, 0.04, len]} />
                <meshStandardMaterial color="#8a93a3" metalness={0.6} roughness={0.4} />
              </mesh>
            ))}
            {Array.from({ length: Math.floor(len / 0.9) + 1 }, (_, k) => {
              const t = (k * 0.9) / len;
              return (
                <mesh key={k} position={[ax + (bx - ax) * t, 0.42, ay + (by - ay) * t]} castShadow>
                  <boxGeometry args={[0.06, 0.84, 0.06]} />
                  <meshStandardMaterial color="#6f7888" metalness={0.5} roughness={0.5} />
                </mesh>
              );
            })}
          </group>
        );
      })}

      {TREES.map(([x, y, s], i) => (
        <Tree key={i} x={x} y={y} s={s} seed={i} />
      ))}
      {LAMPS.map(([x, y], i) => (
        <StreetLamp key={i} x={x} y={y} />
      ))}
      <Bench x={8.3} y={15.3} />
      <Bench x={18.2} y={15.3} />
    </group>
  );
});

function Tree({ x, y, s, seed }: { x: number; y: number; s: number; seed: number }) {
  const greens = ["#3f8f4e", "#4a9a55", "#357a44", "#5aa65e"];
  return (
    <group position={[x, 0, y]} scale={s}>
      {/* tree pit */}
      <mesh position={[0, 0.02, 0]} rotation-x={-Math.PI / 2} receiveShadow>
        <circleGeometry args={[0.45, 20]} />
        <meshStandardMaterial color="#2c2118" roughness={1} />
      </mesh>
      <mesh position={[0, 0.7, 0]} castShadow>
        <cylinderGeometry args={[0.07, 0.11, 1.4, 8]} />
        <meshStandardMaterial color="#5a3d28" roughness={0.9} />
      </mesh>
      {[
        [0, 1.75, 0, 0.75],
        [0.3, 1.45, 0.15, 0.55],
        [-0.28, 1.5, -0.12, 0.5],
        [0.05, 2.2, -0.05, 0.5],
      ].map(([px, py, pz, r], i) => (
        <mesh key={i} position={[px, py, pz]} castShadow>
          <icosahedronGeometry args={[r, 0]} />
          <meshStandardMaterial color={greens[(i + seed) % greens.length]} roughness={0.85} flatShading />
        </mesh>
      ))}
    </group>
  );
}

function StreetLamp({ x, y }: { x: number; y: number }) {
  return (
    <group position={[x, 0, y]}>
      <mesh position={[0, 1.6, 0]} castShadow>
        <cylinderGeometry args={[0.045, 0.06, 3.2, 10]} />
        <meshStandardMaterial color="#2b303b" metalness={0.6} roughness={0.4} />
      </mesh>
      <mesh position={[0, 3.2, -0.25]} rotation-x={Math.PI / 2}>
        <cylinderGeometry args={[0.03, 0.03, 0.5, 8]} />
        <meshStandardMaterial color="#2b303b" metalness={0.6} roughness={0.4} />
      </mesh>
      <mesh position={[0, 3.15, -0.5]}>
        <boxGeometry args={[0.32, 0.1, 0.2]} />
        <meshStandardMaterial color="#20242d" metalness={0.5} />
      </mesh>
      <mesh position={[0, 3.09, -0.5]} rotation-x={Math.PI / 2}>
        <planeGeometry args={[0.26, 0.14]} />
        <meshBasicMaterial color={glow("#ffd59a", 4)} toneMapped={false} />
      </mesh>
      <LightCone position={[0, 3.08, -0.5]} height={3.05} top={0.12} bottom={1.15} color="#ffcf8f" opacity={0.22} />
      <LightPool position={[0, 0.02, -0.5]} radius={1.6} color="#ffcc88" opacity={0.55} />
    </group>
  );
}

function Bench({ x, y }: { x: number; y: number }) {
  return (
    <group position={[x, 0, y]}>
      <mesh position={[0, 0.42, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.3, 0.06, 0.38]} />
        <meshStandardMaterial color="#7a5233" roughness={0.7} />
      </mesh>
      <mesh position={[0, 0.68, 0.17]} castShadow>
        <boxGeometry args={[1.3, 0.3, 0.05]} />
        <meshStandardMaterial color="#7a5233" roughness={0.7} />
      </mesh>
      {[-0.55, 0.55].map((dx) => (
        <mesh key={dx} position={[dx, 0.21, 0]} castShadow>
          <boxGeometry args={[0.06, 0.42, 0.36]} />
          <meshStandardMaterial color="#2b303b" metalness={0.5} />
        </mesh>
      ))}
    </group>
  );
}
