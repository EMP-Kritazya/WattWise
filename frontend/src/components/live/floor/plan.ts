import type { DeviceMeta } from "@/hooks/useDeviceMeta";
import type { Category } from "@/types";

// The restaurant the 3D floor draws. Static scenery only: every number shown on it comes from ticks.
// Plan coordinates are metres: x along the back wall, y toward the camera, z up.
// (In three.js space that is X = x, Y = z, Z = y.)
//
//   y=0 ┌──────── Kitchen ────────┬── Cold ──┬── Dish ──┐
//       │ cook line along the back│ storage  │  room    │
//   y=5 │                         ├──────────┴──────────┤  ┌ Roof
//   y=7 ├── Office ──┬────────────┤     Dining room     │  │ units
//       │   (hub)    │  Dining    │                     │  │ (HVAC)
//  y=13 └────────────┴────────────┴─────────────────────┘  └
//      x=0          x=5          x=10       x=15       x=21

export type Pt = [number, number];

export interface Box {
  x: number;
  y: number;
  z?: number;
  /** Size along x */
  w: number;
  /** Size along y */
  d: number;
  h: number;
}

/** Footprint of the building, for the cap outline and camera framing. */
export const FOOTPRINT = { x: 0, y: 0, w: 21, d: 13 };

export type FloorKind = "kitchen" | "cold" | "dish" | "office" | "dining" | "pad";

export interface Room {
  label: string;
  kind: FloorKind;
  x: number;
  y: number;
  w: number;
  d: number;
}

export const ROOMS: Room[] = [
  { label: "Kitchen", kind: "kitchen", x: 0, y: 0, w: 10, d: 7 },
  { label: "Cold storage", kind: "cold", x: 10, y: 0, w: 5, d: 5 },
  { label: "Dish room", kind: "dish", x: 15, y: 0, w: 6, d: 5 },
  { label: "Office · hub", kind: "office", x: 0, y: 7, w: 5, d: 6 },
  { label: "Dining room", kind: "dining", x: 10, y: 5, w: 11, d: 8 },
  { label: "", kind: "dining", x: 5, y: 7, w: 5, d: 6 },
  { label: "Roof units", kind: "pad", x: 21.8, y: 5.4, w: 2.6, d: 7.2 },
];

const T = 0.22; // wall thickness

/** Tall walls along the two back edges. */
export const BACK_WALLS: Box[] = [
  { x: -T, y: -T, w: 21 + T, d: T, h: 2.8 },
  { x: -T, y: 0, w: T, d: 13, h: 2.8 },
];

/** Windows on the inside of the back walls: [x0, x1] along the wall at y = 0, or [y0, y1] along the wall at x = 0. */
export const WINDOWS: { wall: "x" | "y"; from: number; to: number; z0: number; z1: number }[] = [
  { wall: "x", from: 11.2, to: 13.6, z0: 1.5, z1: 2.3 },
  { wall: "x", from: 16.3, to: 19.4, z0: 1.2, z1: 2.3 },
  { wall: "y", from: 8.2, to: 10.8, z0: 1.0, z1: 2.2 },
  { wall: "y", from: 11.3, to: 12.6, z0: 1.0, z1: 2.2 },
];

// Interior walls are low (cut-away dollhouse view) so you can see into every room. [x0, y0, x1, y1, height]
const INNER_WALLS: [number, number, number, number, number][] = [
  [0, 7, 5, 7, 1],
  [5, 7, 6.5, 7, 1],
  [8.5, 7, 10, 7, 1], // gap 6.5–8.5 is the pass to the dining room
  [10, 0, 10, 3.6, 1],
  [10, 4.6, 10, 7, 1], // door into cold storage
  [15, 0, 15, 5, 1],
  [10, 5, 15, 5, 1],
  [15, 5, 17, 5, 1],
  [18.5, 5, 21, 5, 1], // door into the dish room
  [5, 7, 5, 9, 1],
  [5, 10, 5, 13, 1], // office door
  [0, 13, 21, 13, 0.18], // front curb
  [21, 0, 21, 13, 0.18], // right curb
];

export const WALLS: Box[] = INNER_WALLS.map(([x0, y0, x1, y1, h]) =>
  y0 === y1 ? { x: x0, y: y0 - T / 2, w: x1 - x0, d: T, h } : { x: x0 - T / 2, y: y0, w: T, d: y1 - y0, h },
);

export type PropKind = "steel" | "darkWood" | "wood" | "chair" | "pot" | "leaves";

export interface Prop {
  box: Box;
  kind: PropKind;
}

function plant(x: number, y: number): Prop[] {
  return [
    { box: { x, y, w: 0.5, d: 0.5, h: 0.45 }, kind: "pot" },
    { box: { x: x - 0.1, y: y - 0.1, z: 0.45, w: 0.7, d: 0.7, h: 0.65 }, kind: "leaves" },
  ];
}

// ---------- dining tables, chairs, seats ----------

export const TABLES: Pt[] = [
  [11.4, 7.4],
  [13.9, 7.4],
  [16.4, 7.4],
  [18.9, 7.4],
  [11.4, 10.4],
  [13.9, 10.4],
  [16.4, 10.4],
  [18.9, 10.4],
  [6.0, 8.6],
  [8.4, 8.6],
  [6.0, 11.2],
  [8.4, 11.2],
];
export const TABLE_SIZE = 1;
const CHAIR = 0.42;

/** Chair corners around a table: back, front, left, right. */
const chairSpots = ([tx, ty]: Pt): Pt[] => [
  [tx + 0.29, ty - 0.56],
  [tx + 0.29, ty + 1.14],
  [tx - 0.56, ty + 0.29],
  [tx + 1.14, ty + 0.29],
];

/** Rotation (about the vertical axis) that turns a chair to face its table, in chairSpots order. */
const CHAIR_FACING = [0, Math.PI, Math.PI / 2, -Math.PI / 2];

export interface Seat {
  /** Centre of the chair */
  at: Pt;
  /** Rotation so the chair (and whoever sits in it) faces the table */
  rot: number;
}

export const SEATS: Seat[] = TABLES.flatMap((t) =>
  chairSpots(t).map(([x, y], i): Seat => ({ at: [x + CHAIR / 2, y + CHAIR / 2], rot: CHAIR_FACING[i] })),
);

/** A fixed shuffle of the seats, so diners fill the room in a natural-looking order. */
export const SEAT_ORDER: number[] = (() => {
  const order = SEATS.map((_, i) => i);
  let s = 7;
  for (let i = order.length - 1; i > 0; i--) {
    s = (Math.imul(s, 1103515245) + 12345) >>> 0;
    const j = s % (i + 1);
    [order[i], order[j]] = [order[j], order[i]];
  }
  return order;
})();

/** Simple solid furniture. Tables, chairs and the detailed fittings are drawn in Furniture.tsx. */
export const PROPS: Prop[] = [
  { box: { x: 3.2, y: 3.4, w: 4.2, d: 1.2, h: 0.9 }, kind: "steel" }, // prep island
  { box: { x: 11, y: 5.35, w: 6.5, d: 0.8, h: 1.05 }, kind: "darkWood" }, // bar
  { box: { x: 0.8, y: 8.6, w: 2.8, d: 1.1, h: 0.75 }, kind: "darkWood" }, // office desk
  { box: { x: 20.1, y: 12.1, w: 0.7, d: 0.5, h: 1.1 }, kind: "darkWood" }, // host stand
  ...plant(19.4, 5.45),
  ...plant(10.3, 12.3),
  ...plant(4.1, 12.2),
];

// ---------- the hub (simulated ESP32) ----------

export const HUB_BOX: Box = { x: 1.5, y: 8.8, z: 0.75, w: 0.9, d: 0.55, h: 0.3 };
/** Where every cable meets on the floor (front of the office desk). */
export const HUB_FLOOR: Pt = [1.95, 9.95];

// ---------- equipment placement ----------

type ZoneId = "cookLine" | "reachIns" | "coldRoom" | "dishRoom" | "roof" | "misc";

interface Zone {
  x: number;
  y: number;
  axis: "x" | "y";
  length: number;
  depth: number;
  maxW: number;
  gap: number;
}

const ZONES: Record<ZoneId, Zone> = {
  cookLine: { x: 0.4, y: 0.3, axis: "x", length: 9.2, depth: 1.25, maxW: 1.7, gap: 0.3 },
  reachIns: { x: 2.2, y: 5.6, axis: "x", length: 4.0, depth: 0.9, maxW: 1.2, gap: 0.3 },
  coldRoom: { x: 10.4, y: 0.4, axis: "x", length: 4.2, depth: 2.3, maxW: 2.3, gap: 0.3 },
  dishRoom: { x: 15.5, y: 0.4, axis: "x", length: 5.1, depth: 1.3, maxW: 1.6, gap: 0.35 },
  roof: { x: 22.2, y: 5.8, axis: "y", length: 6.4, depth: 1.8, maxW: 1.8, gap: 0.45 },
  misc: { x: 0.6, y: 11.3, axis: "x", length: 3.6, depth: 0.9, maxW: 1.1, gap: 0.3 },
};

const TYPE_ZONE: Record<string, ZoneId | "lights"> = {
  fryer: "cookLine",
  grill: "cookLine",
  oven: "cookLine",
  reach_in_fridge: "reachIns",
  walk_in_cooler: "coldRoom",
  freezer: "coldRoom",
  dishwasher: "dishRoom",
  water_heater: "dishRoom",
  ice_machine: "dishRoom",
  hvac: "roof",
  kitchen_exhaust: "roof",
  other_equipment: "misc",
  lights: "lights",
};

const CATEGORY_ZONE: Record<Category, ZoneId | "lights"> = {
  cooking: "cookLine",
  refrigeration: "coldRoom",
  water_heating: "dishRoom",
  cooling: "roof",
  lighting: "lights",
  other: "misc",
};

const TYPE_HEIGHT: Record<string, number> = {
  fryer: 1.0,
  grill: 0.95,
  oven: 1.35,
  reach_in_fridge: 1.9,
  walk_in_cooler: 2.2,
  freezer: 1.7,
  dishwasher: 1.45,
  water_heater: 1.9,
  ice_machine: 1.5,
  hvac: 1.2,
  kitchen_exhaust: 0.9,
  other_equipment: 1.0,
};

export interface PlacedDevice {
  meta: DeviceMeta;
  box: Box;
}

export interface PlacedLight {
  meta: DeviceMeta;
  /** Indexes into TABLES of the pendant lamps this lights unit controls. */
  tables: number[];
}

export interface Placement {
  boxes: PlacedDevice[];
  lights: PlacedLight[];
}

/** Lay each device out in its room: units of a type share their zone evenly, so any count from the Builder fits. */
export function placeDevices(metas: DeviceMeta[]): Placement {
  const byZone = new Map<ZoneId, DeviceMeta[]>();
  const lightMetas: DeviceMeta[] = [];
  for (const m of metas) {
    const zone = TYPE_ZONE[m.device.type_id] ?? CATEGORY_ZONE[m.category];
    if (zone === "lights") lightMetas.push(m);
    else byZone.set(zone, [...(byZone.get(zone) ?? []), m]);
  }

  const boxes: PlacedDevice[] = [];
  for (const [id, list] of byZone) {
    const z = ZONES[id];
    const slot = z.length / list.length;
    const size = Math.min(z.maxW, slot - z.gap);
    list.forEach((meta, i) => {
      const offset = i * slot + (slot - size) / 2;
      const h = TYPE_HEIGHT[meta.device.type_id] ?? 1.1;
      const box: Box =
        z.axis === "x" ? { x: z.x + offset, y: z.y, w: size, d: z.depth, h } : { x: z.x, y: z.y + offset, w: z.depth, d: size, h };
      boxes.push({ meta, box });
    });
  }

  const lights = lightMetas.map((meta, i) => ({
    meta,
    tables: TABLES.map((_, t) => t).filter((t) => t % lightMetas.length === i),
  }));
  return { boxes, lights };
}

/** Where a device's cable starts on the floor. */
export function cableStart(p: PlacedDevice): Pt {
  return [p.box.x + p.box.w / 2, p.box.y + p.box.d / 2];
}

/** The cable route on the floor: down toward the hub's row, then along it to the hub. */
export function cableRoute([x, y]: Pt): Pt[] {
  const [hx, hy] = HUB_FLOOR;
  return [
    [x, y],
    [x, hy],
    [hx, hy],
  ];
}
