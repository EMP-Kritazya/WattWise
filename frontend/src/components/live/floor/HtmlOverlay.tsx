import { useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useFrame, useThree } from "@react-three/fiber";
import { Group, Vector3 } from "three";
import { create } from "zustand";

interface Label { id: string; element: HTMLDivElement; content: ReactNode }
const useLabels = create<{ labels: Map<HTMLDivElement, Label>; put: (label: Label) => void; remove: (element: HTMLDivElement) => void }>((set) => ({
  labels: new Map(),
  put: (label) => set((state) => ({ labels: new Map(state.labels).set(label.element, label) })),
  remove: (element) => set((state) => {
    const labels = new Map(state.labels); labels.delete(element); return { labels };
  }),
}));

/** Labels belong to the application's DOM root, so removing a 3D object never synchronously unmounts another root. */
export function HtmlOverlays() {
  const labels = useLabels((state) => state.labels);
  return <>{Array.from(labels.values(), ({ id, element, content }) => createPortal(content, element, id))}</>;
}

interface HtmlProps {
  position: [number, number, number];
  children: ReactNode;
  zIndexRange?: [number, number];
  pointerEvents?: CSSProperties["pointerEvents"];
  style?: CSSProperties;
}

/** Screen-facing labels only: projects an anchor while preserving the floor's existing label markup. */
export function Html({ position, children, zIndexRange = [30, 10], pointerEvents = "none", style }: HtmlProps) {
  const id = useId();
  const group = useRef<Group>(null);
  const [element] = useState(() => document.createElement("div"));
  const { gl } = useThree();
  const world = useMemo(() => new Vector3(), []);
  const projected = useMemo(() => new Vector3(), []);
  const cameraPosition = useMemo(() => new Vector3(), []);

  useLayoutEffect(() => {
    const target = gl.domElement.parentElement;
    element.dataset.floorLabel = id;
    Object.assign(element.style, { position: "absolute", top: "0", left: "0", transformOrigin: "0 0", display: "none" });
    target?.appendChild(element);
    return () => { useLabels.getState().remove(element); element.remove(); };
  }, [element, gl, id]);

  useLayoutEffect(() => {
    useLabels.getState().put({ id, element, content: <div style={{ ...style, pointerEvents }}>{children}</div> });
    element.style.pointerEvents = pointerEvents ?? "none";
  }, [children, element, id, pointerEvents, style]);

  useFrame(({ camera, size }) => {
    const anchor = group.current;
    if (!anchor) return;
    anchor.updateWorldMatrix(true, false);
    world.setFromMatrixPosition(anchor.matrixWorld);
    projected.copy(world).project(camera);
    let visible = projected.z >= -1 && projected.z <= 1;
    for (let parent: Group | null = anchor; parent; parent = parent.parent as Group | null) visible &&= parent.visible;
    element.style.display = visible ? "block" : "none";
    element.style.transform = `translate3d(${(projected.x + 1) * size.width / 2}px,${(1 - projected.y) * size.height / 2}px,0)`;
    camera.getWorldPosition(cameraPosition);
    const fraction = (world.distanceTo(cameraPosition) - camera.near) / (camera.far - camera.near);
    element.style.zIndex = String(Math.round(zIndexRange[0] + fraction * (zIndexRange[1] - zIndexRange[0])));
  });
  return <group ref={group} position={position} />;
}
