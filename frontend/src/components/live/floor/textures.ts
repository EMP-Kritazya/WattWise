import { CanvasTexture, RepeatWrapping, SRGBColorSpace, type Texture } from "three";

// Procedural textures drawn on a canvas once (no image downloads). Each is a seamless tile; callers set `repeat`.

const cache = new Map<string, Texture>();

function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function make(key: string, size: number, draw: (ctx: CanvasRenderingContext2D, r: () => number) => void): Texture {
  const hit = cache.get(key);
  if (hit) return hit;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  draw(ctx, rng(key.length * 7919));
  const tex = new CanvasTexture(canvas);
  tex.colorSpace = SRGBColorSpace;
  tex.wrapS = tex.wrapT = RepeatWrapping;
  tex.anisotropy = 8;
  cache.set(key, tex);
  return tex;
}

/** Fresh texture object sharing the cached image, so each surface can have its own repeat. */
export function texture(kind: TextureKind, repeatX: number, repeatY: number): Texture {
  const t = BUILDERS[kind]().clone();
  t.repeat.set(repeatX, repeatY);
  t.needsUpdate = true;
  return t;
}

export type TextureKind = "tile" | "coldTile" | "planks" | "carpet" | "concrete" | "grass" | "asphalt";

const BUILDERS: Record<TextureKind, () => Texture> = {
  // Kitchen quarry tiles: 2×2 tiles per texture, grout lines, slight tone variation.
  tile: () =>
    make("tile", 256, (ctx, r) => {
      for (let i = 0; i < 2; i++)
        for (let j = 0; j < 2; j++) {
          const l = 34 + r() * 6;
          ctx.fillStyle = `hsl(220 8% ${l}%)`;
          ctx.fillRect(i * 128, j * 128, 128, 128);
        }
      ctx.strokeStyle = "rgba(10,12,18,0.55)";
      ctx.lineWidth = 6;
      for (let k = 0; k <= 256; k += 128) {
        ctx.beginPath();
        ctx.moveTo(k, 0);
        ctx.lineTo(k, 256);
        ctx.moveTo(0, k);
        ctx.lineTo(256, k);
        ctx.stroke();
      }
      speckle(ctx, r, 256, 900, 0.05);
    }),
  coldTile: () =>
    make("coldTile", 256, (ctx, r) => {
      ctx.fillStyle = "hsl(205 18% 38%)";
      ctx.fillRect(0, 0, 256, 256);
      ctx.strokeStyle = "rgba(8,14,22,0.5)";
      ctx.lineWidth = 4;
      for (let k = 0; k <= 256; k += 64) {
        ctx.beginPath();
        ctx.moveTo(k, 0);
        ctx.lineTo(k, 256);
        ctx.moveTo(0, k);
        ctx.lineTo(256, k);
        ctx.stroke();
      }
      speckle(ctx, r, 256, 600, 0.04);
    }),
  // Dining room oak planks running along x.
  planks: () =>
    make("planks", 512, (ctx, r) => {
      const rows = 8;
      const h = 512 / rows;
      for (let row = 0; row < rows; row++) {
        let x = -r() * 200;
        while (x < 512) {
          const w = 160 + r() * 200;
          const l = 30 + r() * 10;
          ctx.fillStyle = `hsl(${26 + r() * 6} ${45 + r() * 10}% ${l}%)`;
          ctx.fillRect(x, row * h, w, h);
          // grain
          ctx.strokeStyle = `rgba(40,20,8,${0.12 + r() * 0.1})`;
          ctx.lineWidth = 1;
          for (let g = 0; g < 5; g++) {
            const y = row * h + 4 + r() * (h - 8);
            ctx.beginPath();
            ctx.moveTo(x, y);
            ctx.bezierCurveTo(x + w * 0.3, y + (r() - 0.5) * 6, x + w * 0.7, y + (r() - 0.5) * 6, x + w, y);
            ctx.stroke();
          }
          ctx.fillStyle = "rgba(20,10,4,0.6)";
          ctx.fillRect(x, row * h, 2, h);
          x += w;
        }
        ctx.fillStyle = "rgba(20,10,4,0.55)";
        ctx.fillRect(0, row * h, 512, 2);
      }
    }),
  carpet: () =>
    make("carpet", 256, (ctx, r) => {
      ctx.fillStyle = "hsl(245 18% 26%)";
      ctx.fillRect(0, 0, 256, 256);
      speckle(ctx, r, 256, 5000, 0.08);
    }),
  concrete: () =>
    make("concrete", 256, (ctx, r) => {
      ctx.fillStyle = "hsl(220 6% 46%)";
      ctx.fillRect(0, 0, 256, 256);
      speckle(ctx, r, 256, 3000, 0.07);
      ctx.strokeStyle = "rgba(20,22,28,0.45)";
      ctx.lineWidth = 3;
      ctx.strokeRect(0, 0, 256, 256);
    }),
  grass: () =>
    make("grass", 256, (ctx, r) => {
      ctx.fillStyle = "hsl(115 30% 24%)";
      ctx.fillRect(0, 0, 256, 256);
      for (let i = 0; i < 2500; i++) {
        ctx.fillStyle = `hsl(${100 + r() * 30} ${30 + r() * 20}% ${18 + r() * 16}%)`;
        ctx.fillRect(r() * 256, r() * 256, 2, 3);
      }
    }),
  asphalt: () =>
    make("asphalt", 256, (ctx, r) => {
      ctx.fillStyle = "hsl(225 8% 17%)";
      ctx.fillRect(0, 0, 256, 256);
      speckle(ctx, r, 256, 4000, 0.06);
    }),
};

function speckle(ctx: CanvasRenderingContext2D, r: () => number, size: number, n: number, alpha: number) {
  for (let i = 0; i < n; i++) {
    ctx.fillStyle = r() > 0.5 ? `rgba(255,255,255,${alpha})` : `rgba(0,0,0,${alpha})`;
    ctx.fillRect(r() * size, r() * size, 1 + r() * 2, 1 + r() * 2);
  }
}

/** Vertical fade for light cones: opaque at the top (v = 1, the lamp), clear at the bottom. Used as an alphaMap. */
export function coneGradient(): Texture {
  return make("coneGradient", 64, (ctx) => {
    const g = ctx.createLinearGradient(0, 0, 0, 64);
    g.addColorStop(0, "rgb(255,255,255)");
    g.addColorStop(0.35, "rgb(120,120,120)");
    g.addColorStop(1, "rgb(0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 64, 64);
  });
}

/** A soft round glow (white centre fading out) for light pools on the floor. */
export function glowSprite(): Texture {
  return make("glow", 128, (ctx) => {
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.4, "rgba(255,255,255,0.45)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
  });
}
