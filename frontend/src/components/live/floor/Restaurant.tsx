import { useMemo, type RefObject } from "react";
import { Line } from "@react-three/drei";
import type { Group } from "three";
import type { Lane, TickState } from "@/types";
import { useLive } from "@/data";
import { Diners, GuestQueue, Hub3D, LaneTitle, Lamps } from "./Ambient";
import { Device3D, type TagMode } from "./Device3D";
import { SEAT_ORDER, TABLES, cableStart, cableRoute, type Placement } from "./plan";
import { Scenery } from "./Scenery";
import { useLabelOffsets, type LabelAnchor } from "./useLabelOffsets";
import { REDUCED_TEAL } from "./palette";

export interface RestaurantProps {
  lane: Lane;
  tick: TickState | null;
  placement: Placement;
  /** "full" for the single big view; "compact" in side-by-side mode (fewer labels). */
  detail: "full" | "compact";
  selected: string | null;
  onSelect: (id: string | null) => void;
  deviceRefs?: RefObject<Map<string, Group>>;
  position?: [number, number, number];
  /** Show the floating labels (kW tags, hub card, cap badge, room names). Hover/click details always work. */
  labels: boolean;
  /** Equipment focus: hide furniture, darken floors, so only appliances stand out. */
  focus: boolean;
}

/** One restaurant, drawn from one lane's tick. */
export function Restaurant({ lane, tick, placement, detail, selected, onSelect, deviceRefs, position, labels, focus }: RestaurantProps) {
  const requestedLargeSurge = useLive((state) => state.surge_request.some((request) => !request.consumed && request.customers >= 40));
  const readings = useMemo(() => new Map((tick?.hub.devices ?? []).map((r) => [r.device_id, r] as const)), [tick]);
  const deviceCount = placement.boxes.length + placement.lights.length;
  const customersPerHour = tick?.customers_per_hour ?? 0;
  // Visual occupancy only; the displayed customer number remains the engine-provided value in the HUD.
  const occupied = useMemo(() => {
    const seats = Math.min(SEAT_ORDER.length, Math.round(customersPerHour / 3));
    return new Set(SEAT_ORDER.slice(0, seats));
  }, [customersPerHour]);
  const queueCount = requestedLargeSurge ? 6 : Math.min(6, Math.max(0, Math.ceil((customersPerHour - 82) / 7)));

  // Every working appliance is labelled (name + kW); WattWise's changes get the action label. Off: no label.
  const tags = useMemo(() => {
    const out = new Map<string, TagMode>();
    for (const p of placement.boxes) {
      const id = p.meta.device.device_id;
      const r = readings.get(id);
      const acting = lane === "with" && (r?.state === "reduced" || r?.state === "waiting");
      const working = r != null && r.state !== "off" && r.power_kw > 0;
      out.set(id, !labels || !r || detail === "compact" ? "none" : acting ? "action" : working ? "status" : "none");
    }
    return out;
  }, [placement, readings, lane, labels, detail]);

  const [ox, oy, oz] = position ?? [0, 0, 0];
  const anchors: LabelAnchor[] = useMemo(
    () =>
      placement.boxes
        .filter((p) => tags.get(p.meta.device.device_id) !== "none")
        .map((p) => ({
          id: p.meta.device.device_id,
          at: [ox + p.box.x + p.box.w / 2, oy + p.box.h + 0.3, oz + p.box.y + p.box.d / 2] as [number, number, number],
          width: (p.meta.device.name.length + (tags.get(p.meta.device.device_id) === "action" ? 22 : 9)) * 7 + 28,
        })),
    [placement, tags, ox, oy, oz],
  );
  const lifts = useLabelOffsets(anchors);

  return (
    <group position={position}>
      <Scenery roomLabels={labels && focus && detail === "full"} focus={focus} />

      {placement.boxes.map((p) => {
        const id = p.meta.device.device_id;
        const r = readings.get(id);
        const tag = tags.get(id) ?? "none";
        return (
          <Device3D
            key={id}
            ref={(g) => {
              if (!deviceRefs?.current) return;
              if (g) deviceRefs.current.set(id, g);
              else deviceRefs.current.delete(id);
            }}
            placed={p}
            reading={r}
            tag={tag}
            labelLift={lifts[id] ?? 0}
            selected={selected === id}
            interactive={true}
            onSelect={onSelect}
          />
        );
      })}

      {placement.boxes.map((p) => {
        const id = p.meta.device.device_id;
        const reduced = readings.get(id)?.state === "reduced";
        return (
          <Line
            key={`cable:${id}`}
            points={cableRoute(cableStart(p)).map(([x, y]) => [x, 0.025, y] as [number, number, number])}
            color={reduced ? REDUCED_TEAL : "#94a3b8"}
            transparent
            opacity={reduced ? 0.9 : selected === id ? 0.8 : 0.12}
            lineWidth={reduced ? 2.4 : 1}
            dashed={reduced}
            dashSize={0.22}
            gapSize={0.12}
          />
        );
      })}
      {placement.lights.map((l) => {
        const id = l.meta.device.device_id;
        const r = readings.get(id);
        return (
          <group
            key={id}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(selected === id ? null : id);
            }}
          >
            {!focus && <Lamps tables={l.tables} level={r && l.meta.device.rated_kw > 0 ? Math.min(1, r.power_kw / l.meta.device.rated_kw) : 0} />}
            {selected === id &&
              l.tables.map((t) => (
                <mesh key={t} position={[TABLES[t][0] + 0.5, 0.8, TABLES[t][1] + 0.5]} rotation-x={-Math.PI / 2}>
                  <ringGeometry args={[0.65, 0.7, 32]} />
                  <meshBasicMaterial color="#ffffff" />
                </mesh>
              ))}
          </group>
        );
      })}
      {!focus && <Diners occupied={occupied} />}
      {!focus && <GuestQueue count={queueCount} />}
      <Hub3D totalKw={tick?.hub.total_kw} deviceCount={deviceCount} showLabel={labels} />
      {detail === "compact" && <LaneTitle lane={lane} />}
    </group>
  );
}
