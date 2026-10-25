import { memo } from "react";
import { Instance, Instances } from "@react-three/drei";
import { Color } from "three";
import { LightCone, LightPool } from "./Effects3D";
import { SEATS, TABLES, TABLE_SIZE } from "./plan";
import { Toon } from "./toon";

// Detailed fittings, drawn with instancing so hundreds of small parts stay a handful of draw calls.

const glow = (hex: string, k: number) => new Color(hex).multiplyScalar(k);

const BAR_STOOLS = [11.6, 12.85, 14.1, 15.35, 16.6];
const BOTTLE_COLORS = ["#7fbf6a", "#c98b3a", "#e6d7a3", "#8a3b2f", "#4f7fbf", "#d9a441", "#5c3a21"];
const BOTTLES = Array.from({ length: 2 * 22 }, (_, i) => ({
  x: 11.35 + (i % 22) * 0.27 + ((i * 7) % 3) * 0.02,
  shelf: Math.floor(i / 22),
  color: BOTTLE_COLORS[(i * 5) % BOTTLE_COLORS.length],
  h: 0.26 + ((i * 3) % 4) * 0.03,
}));
const POTS = [
  [0.22, 1.62, 2.3, 0.16],
  [0.22, 1.62, 2.8, 0.13],
  [0.22, 1.62, 3.3, 0.18],
  [0.22, 2.02, 2.5, 0.12],
  [0.22, 2.02, 3.05, 0.15],
] as const;

export const Furniture = memo(function Furniture() {
  return (
    <group>
      <DiningSets />
      <Bar />
      <KitchenFittings />
      <Office />
    </group>
  );
});

function DiningSets() {
  return (
    <group>
      {/* Table tops, pedestals and bases */}
      <Instances limit={TABLES.length} castShadow receiveShadow>
        <boxGeometry args={[TABLE_SIZE, 0.05, TABLE_SIZE]} />
        <Toon color="#C98B5E" />
        {TABLES.map(([x, y], i) => (
          <Instance key={i} position={[x + 0.5, 0.745, y + 0.5]} />
        ))}
      </Instances>
      <Instances limit={TABLES.length} castShadow>
        <cylinderGeometry args={[0.05, 0.06, 0.72, 10]} />
        <Toon color="#9C6644" />
        {TABLES.map(([x, y], i) => (
          <Instance key={i} position={[x + 0.5, 0.36, y + 0.5]} />
        ))}
      </Instances>
      <Instances limit={TABLES.length} receiveShadow>
        <cylinderGeometry args={[0.28, 0.3, 0.03, 20]} />
        <Toon color="#9C6644" />
        {TABLES.map(([x, y], i) => (
          <Instance key={i} position={[x + 0.5, 0.015, y + 0.5]} />
        ))}
      </Instances>

      {/* Chairs (seat, back, legs) and a place setting in front of each */}
      <Instances limit={SEATS.length} castShadow receiveShadow>
        <boxGeometry args={[0.42, 0.05, 0.42]} />
        <Toon color="#F4A261" />
        {SEATS.map((s, i) => (
          <group key={i} position={[s.at[0], 0, s.at[1]]} rotation-y={s.rot}>
            <Instance position={[0, 0.45, 0]} />
          </group>
        ))}
      </Instances>
      <Instances limit={SEATS.length} castShadow>
        <boxGeometry args={[0.42, 0.46, 0.05]} />
        <Toon color="#E7904F" />
        {SEATS.map((s, i) => (
          <group key={i} position={[s.at[0], 0, s.at[1]]} rotation-y={s.rot}>
            <Instance position={[0, 0.7, -0.19]} />
          </group>
        ))}
      </Instances>
      <Instances limit={SEATS.length * 4} castShadow>
        <boxGeometry args={[0.04, 0.45, 0.04]} />
        <Toon color="#9C6644" />
        {SEATS.map((s, i) => (
          <group key={i} position={[s.at[0], 0, s.at[1]]} rotation-y={s.rot}>
            {[
              [-0.17, -0.17],
              [0.17, -0.17],
              [-0.17, 0.17],
              [0.17, 0.17],
            ].map(([lx, lz], k) => (
              <Instance key={k} position={[lx, 0.225, lz]} />
            ))}
          </group>
        ))}
      </Instances>
      <Instances limit={SEATS.length} receiveShadow>
        <cylinderGeometry args={[0.12, 0.1, 0.015, 20]} />
        <Toon color="#f2f0ea" roughness={0.3} />
        {SEATS.map((s, i) => (
          <group key={i} position={[s.at[0], 0, s.at[1]]} rotation-y={s.rot}>
            <Instance position={[0, 0.778, 0.55]} />
          </group>
        ))}
      </Instances>
      <Instances limit={SEATS.length}>
        <cylinderGeometry args={[0.03, 0.025, 0.11, 10]} />
        <meshPhysicalMaterial color="#cfe6ff" roughness={0.05} transmission={0.6} transparent opacity={0.55} />
        {SEATS.map((s, i) => (
          <group key={i} position={[s.at[0], 0, s.at[1]]} rotation-y={s.rot}>
            <Instance position={[0.17, 0.83, 0.5]} />
          </group>
        ))}
      </Instances>
    </group>
  );
}

function Bar() {
  return (
    <group>
      {/* Bar top and stools */}
      <mesh position={[14.25, 1.075, 5.75]} castShadow receiveShadow>
        <boxGeometry args={[6.7, 0.05, 0.95]} />
        <Toon color="#2b2018" roughness={0.3} metalness={0.2} />
      </mesh>
      <Instances limit={BAR_STOOLS.length} castShadow>
        <cylinderGeometry args={[0.19, 0.17, 0.06, 18]} />
        <Toon color="#7a2f2a" roughness={0.6} />
        {BAR_STOOLS.map((x) => (
          <Instance key={x} position={[x, 0.76, 6.45]} />
        ))}
      </Instances>
      <Instances limit={BAR_STOOLS.length} castShadow>
        <cylinderGeometry args={[0.03, 0.03, 0.74, 8]} />
        <Toon color="#9aa3b2" metalness={0.7} roughness={0.3} />
        {BAR_STOOLS.map((x) => (
          <Instance key={x} position={[x, 0.37, 6.45]} />
        ))}
      </Instances>

      {/* Back bar: two backlit shelves of bottles standing on the low wall */}
      <mesh position={[14.25, 1.6, 5.15]} castShadow>
        <boxGeometry args={[6.4, 1.2, 0.16]} />
        <Toon color="#1e1712" roughness={0.6} />
      </mesh>
      {[0, 1].map((shelf) => (
        <group key={shelf}>
          <mesh position={[14.25, 1.12 + shelf * 0.5, 5.32]}>
            <boxGeometry args={[6.3, 0.03, 0.2]} />
            <Toon color="#3a2a1d" />
          </mesh>
          <mesh position={[14.25, 1.15 + shelf * 0.5, 5.235]}>
            <planeGeometry args={[6.2, 0.06]} />
            <meshBasicMaterial color={glow("#ffb45e", 3.2)} toneMapped={false} />
          </mesh>
        </group>
      ))}
      <Instances limit={BOTTLES.length}>
        <cylinderGeometry args={[0.045, 0.05, 1, 10]} />
        <Toon roughness={0.15} metalness={0.1} transparent opacity={0.9} />
        {BOTTLES.map((b, i) => (
          <Instance key={i} position={[b.x, 1.14 + b.shelf * 0.5 + b.h / 2, 5.33]} scale={[1, b.h, 1]} color={b.color} />
        ))}
      </Instances>
    </group>
  );
}

function KitchenFittings() {
  return (
    <group>
      {/* Range hood over the cook line, with downlights */}
      <mesh position={[5, 2.3, 0.62]} castShadow>
        <boxGeometry args={[9.4, 0.32, 1.24]} />
        <Toon color="#c3c9d2" metalness={0.75} roughness={0.28} />
      </mesh>
      <mesh position={[5, 2.6, 0.35]}>
        <boxGeometry args={[1.2, 0.3, 0.7]} />
        <Toon color="#b5bcc6" metalness={0.75} roughness={0.3} />
      </mesh>
      {[1.4, 3.8, 6.2, 8.6].map((x) => (
        <LightCone key={x} position={[x, 2.14, 0.9]} height={1.1} top={0.12} bottom={0.6} color="#fff3dc" opacity={0.12} />
      ))}

      {/* Wall shelves with pots on the left kitchen wall */}
      {[1.55, 1.95].map((y) => (
        <mesh key={y} position={[0.2, y, 2.9]} castShadow>
          <boxGeometry args={[0.36, 0.04, 2.2]} />
          <Toon color="#c3c9d2" metalness={0.7} roughness={0.3} />
        </mesh>
      ))}
      {POTS.map(([x, y, z, r], i) => (
        <mesh key={i} position={[x, y + r * 0.5 + 0.02, z]} castShadow>
          <cylinderGeometry args={[r, r * 0.92, r, 16]} />
          <Toon color={i % 2 ? "#a7adb6" : "#b7793c"} metalness={0.8} roughness={0.3} />
        </mesh>
      ))}

      {/* Prep island: cutting boards and bowls */}
      {[3.8, 5.5].map((x) => (
        <mesh key={x} position={[x, 0.915, 4.0]} castShadow>
          <boxGeometry args={[0.7, 0.03, 0.45]} />
          <Toon color="#c9a26b" roughness={0.7} />
        </mesh>
      ))}
      {[6.6, 6.95].map((x) => (
        <mesh key={x} position={[x, 0.96, 3.85]} castShadow>
          <sphereGeometry args={[0.12, 16, 10, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2]} />
          <Toon color="#e8e6df" roughness={0.3} side={2} />
        </mesh>
      ))}

      {/* The pass to the dining room: a shelf under orange heat lamps, with plates waiting */}
      <mesh position={[7.5, 1.12, 7]} castShadow receiveShadow>
        <boxGeometry args={[2.1, 0.05, 0.5]} />
        <Toon color="#c3c9d2" metalness={0.75} roughness={0.28} />
      </mesh>
      {[6.95, 8.05].map((x) => (
        <group key={x}>
          <mesh position={[x, 1.75, 7]}>
            <boxGeometry args={[0.5, 0.08, 0.18]} />
            <Toon color="#2b303b" metalness={0.5} />
          </mesh>
          <mesh position={[x, 1.705, 7]} rotation-x={Math.PI / 2}>
            <planeGeometry args={[0.44, 0.12]} />
            <meshBasicMaterial color={glow("#ff7a2a", 4)} toneMapped={false} />
          </mesh>
          <LightCone position={[x, 1.7, 7]} height={0.55} top={0.12} bottom={0.32} color="#ff8a3a" opacity={0.3} />
          <mesh position={[x, 1.155, 7]}>
            <cylinderGeometry args={[0.13, 0.11, 0.02, 20]} />
            <Toon color="#f2f0ea" roughness={0.3} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

function Office() {
  return (
    <group>
      {/* Monitor on the desk, glowing with the dashboard */}
      <mesh position={[2.9, 1.08, 8.85]} castShadow>
        <boxGeometry args={[0.62, 0.38, 0.04]} />
        <Toon color="#14171f" />
      </mesh>
      <mesh position={[2.9, 1.08, 8.873]}>
        <planeGeometry args={[0.56, 0.32]} />
        <meshBasicMaterial color={glow("#5aa0ff", 1.8)} toneMapped={false} />
      </mesh>
      <mesh position={[2.9, 0.83, 8.82]}>
        <boxGeometry args={[0.06, 0.16, 0.06]} />
        <Toon color="#14171f" />
      </mesh>
      <LightPool position={[2.9, 0.765, 9.2]} radius={0.6} color="#5aa0ff" opacity={0.35} />
      {/* Office chair and a filing cabinet */}
      <mesh position={[2.3, 0.48, 10.05]} castShadow>
        <boxGeometry args={[0.48, 0.07, 0.48]} />
        <Toon color="#20242e" />
      </mesh>
      <mesh position={[2.3, 0.78, 10.27]} castShadow>
        <boxGeometry args={[0.46, 0.55, 0.06]} />
        <Toon color="#20242e" />
      </mesh>
      <mesh position={[2.3, 0.24, 10.05]}>
        <cylinderGeometry args={[0.03, 0.03, 0.44, 8]} />
        <Toon color="#5b6475" metalness={0.6} />
      </mesh>
      <mesh position={[0.4, 0.55, 11.9]} castShadow>
        <boxGeometry args={[0.55, 1.1, 0.65]} />
        <Toon color="#5b6475" metalness={0.4} roughness={0.5} />
      </mesh>
    </group>
  );
}
