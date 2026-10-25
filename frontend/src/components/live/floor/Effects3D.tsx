import { useMemo } from "react";
import { AdditiveBlending, DoubleSide } from "three";
import { coneGradient, glowSprite } from "./textures";

// Cheap "volumetric" light: an additive cone that fades from the lamp down to the floor.
// Looks like light in the air without real volumetrics or extra lights. (A custom shader version produced NaNs
// that the bloom pass spread over the whole frame, so this sticks to a standard material with an alpha map.)

export function LightCone({
  position,
  height,
  top,
  bottom,
  color,
  opacity,
}: {
  position: [number, number, number];
  height: number;
  top: number;
  bottom: number;
  color: string;
  opacity: number;
}) {
  const alphaMap = useMemo(() => coneGradient(), []);
  if (opacity <= 0.001) return null;
  // The cone's narrow end is at the lamp; the open base lands on the surface below.
  return (
    <mesh position={[position[0], position[1] - height / 2, position[2]]} renderOrder={2}>
      <cylinderGeometry args={[top, bottom, height, 32, 1, true]} />
      <meshBasicMaterial
        color={color}
        alphaMap={alphaMap}
        transparent
        opacity={opacity}
        blending={AdditiveBlending}
        depthWrite={false}
        side={DoubleSide}
        toneMapped={false}
      />
    </mesh>
  );
}

/** A soft additive pool of light on a surface. */
export function LightPool({
  position,
  radius,
  color,
  opacity,
}: {
  position: [number, number, number];
  radius: number;
  color: string;
  opacity: number;
}) {
  const map = useMemo(() => glowSprite(), []);
  if (opacity <= 0.001) return null;
  return (
    <mesh position={position} rotation-x={-Math.PI / 2} renderOrder={1}>
      <planeGeometry args={[radius * 2, radius * 2]} />
      <meshBasicMaterial map={map} color={color} transparent opacity={opacity} blending={AdditiveBlending} depthWrite={false} toneMapped={false} />
    </mesh>
  );
}
