import type { ThreeElements } from "@react-three/fiber";
import { Outlines } from "@react-three/drei";
import { CanvasTexture, DataTexture, NearestFilter, RedFormat, RepeatWrapping, SRGBColorSpace, type Texture } from "three";
import { INK } from "./palette";

// The Toy Box look (frontend/UI_CONCEPTS.md): flat 3-step toon shading plus ink outlines on every solid object.

/** Three light bands: shadow side, mid, lit. Nearest filtering keeps the steps crisp. */
const TOON_GRADIENT = (() => {
  const t = new DataTexture(new Uint8Array([150, 205, 255]), 3, 1, RedFormat);
  t.minFilter = NearestFilter;
  t.magFilter = NearestFilter;
  t.needsUpdate = true;
  return t;
})();

type ToonProps = ThreeElements["meshToonMaterial"] & {
  /** Accepted (and ignored) so call sites written for meshStandardMaterial keep working. */
  metalness?: number;
  roughness?: number;
  envMapIntensity?: number;
};

/** Drop-in replacement for meshStandardMaterial in the floor: toon shading with the shared gradient. */
export function Toon({ metalness, roughness, envMapIntensity, ...rest }: ToonProps) {
  void metalness;
  void roughness;
  void envMapIntensity;
  return <meshToonMaterial gradientMap={TOON_GRADIENT} {...rest} />;
}

/** Ink outline for a solid mesh (place it as a child of the mesh). `thickness` is in screen pixels. */
export function Ink({ thickness = 2.2, color = INK }: { thickness?: number; color?: string }) {
  return <Outlines thickness={thickness} color={color} />;
}

const patternCache = new Map<string, Texture>();

/** Flat floor patterns: a two-colour checker (1 m tiles) or planks, repeated over the room. */
export function floorPattern(kind: "checker" | "planks", a: string, b: string, repeatX: number, repeatY: number): Texture {
  const key = `${kind}:${a}:${b}:${repeatX}:${repeatY}`;
  const hit = patternCache.get(key);
  if (hit) return hit;
  const c = document.createElement("canvas");
  c.width = 64;
  c.height = 64;
  const g = c.getContext("2d")!;
  if (kind === "checker") {
    g.fillStyle = a;
    g.fillRect(0, 0, 64, 64);
    g.fillStyle = b;
    g.fillRect(32, 0, 32, 32);
    g.fillRect(0, 32, 32, 32);
  } else {
    g.fillStyle = a;
    g.fillRect(0, 0, 64, 64);
    g.fillStyle = b;
    for (let x = 0; x < 64; x += 16) g.fillRect(x, 0, 2, 64);
    for (let y = 0; y < 64; y += 32) g.fillRect(0, y, 64, 1);
  }
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  t.wrapS = t.wrapT = RepeatWrapping;
  t.magFilter = NearestFilter;
  t.repeat.set(repeatX, repeatY);
  patternCache.set(key, t);
  return t;
}
