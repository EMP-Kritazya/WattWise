import { useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Vector3 } from "three";

export interface LabelAnchor {
  id: string;
  /** World position the label points at (top of the appliance). */
  at: [number, number, number];
  /** Rough label width in px, from its text length. */
  width: number;
}

const LABEL_H = 28;
const GAP = 4;
const EVERY_S = 0.2;

/**
 * Keeps floating labels from overlapping: projects each anchor to the screen, places the front-most labels first,
 * and lifts any label that would overlap one already placed. Returns px to lift each label by (0 = sits on its anchor).
 * Re-runs a few times a second so it follows the camera; only re-renders when a lift actually changes.
 */
export function useLabelOffsets(anchors: LabelAnchor[]): Record<string, number> {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const [offsets, setOffsets] = useState<Record<string, number>>({});
  const since = useRef(EVERY_S);
  const v = useRef(new Vector3());

  useFrame((_, dt) => {
    since.current += dt;
    if (since.current < EVERY_S) return;
    since.current = 0;

    const pts = anchors.map((a) => {
      v.current.set(...a.at).project(camera);
      return { ...a, x: ((v.current.x + 1) / 2) * size.width, y: ((1 - v.current.y) / 2) * size.height };
    });
    pts.sort((a, b) => b.y - a.y); // front of the scene (lower on screen) first

    const placed: { x0: number; x1: number; y0: number; y1: number }[] = [];
    const next: Record<string, number> = {};
    for (const p of pts) {
      const x0 = p.x - p.width / 2;
      const x1 = p.x + p.width / 2;
      let bottom = p.y;
      for (let guard = 0; guard < 40; guard++) {
        const hit = placed.find((r) => x0 < r.x1 + GAP && x1 > r.x0 - GAP && bottom > r.y0 - GAP && bottom - LABEL_H < r.y1 + GAP);
        if (!hit) break;
        bottom = hit.y0 - GAP;
      }
      placed.push({ x0, x1, y0: bottom - LABEL_H, y1: bottom });
      next[p.id] = Math.round(p.y - bottom);
    }

    const changed =
      Object.keys(next).length !== Object.keys(offsets).length || Object.entries(next).some(([id, px]) => Math.abs((offsets[id] ?? -1) - px) > 1);
    if (changed) setOffsets(next);
  });

  return offsets;
}
