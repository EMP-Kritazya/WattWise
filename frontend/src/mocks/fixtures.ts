import hubServerRaw from "@fixtures/hub_protocol/server_to_hub.jsonl?raw";
import liveRowsRaw from "@fixtures/spacetime/rows_stream.jsonl?raw";
import viewerWsRaw from "@fixtures/ws/stream.jsonl?raw";
import type { LiveTables, ServerToHubMessage, WsMessage } from "@/types";

export interface RestFixture {
  method: string;
  path: string;
  status: number;
  request: unknown;
  response: unknown;
}

const parseJsonLines = <T,>(raw: string): T[] =>
  raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as T);

const restModules = import.meta.glob("@fixtures/rest/*.json", { eager: true, import: "default" }) as Record<string, RestFixture>;
const tableModules = import.meta.glob("@fixtures/spacetime/tables/*.json", { eager: true, import: "default" }) as Record<
  string,
  unknown[]
>;

const basename = (path: string) => path.slice(path.lastIndexOf("/") + 1, path.lastIndexOf("."));

export const restFixtures = Object.values(restModules);
export const liveRowFrames = parseJsonLines<LiveRowFrame>(liveRowsRaw);
export const viewerWsMessages = parseJsonLines<WsMessage>(viewerWsRaw);
export const hubServerMessages = parseJsonLines<ServerToHubMessage>(hubServerRaw);

export interface LiveRowFrame {
  live_tick: LiveTables["live_tick"];
  tick_history: LiveTables["tick_history"];
  live_device: LiveTables["live_device"];
  live_comparison: LiveTables["live_comparison"][number];
}

export function seedLiveTables(): LiveTables {
  const rows = Object.fromEntries(Object.entries(tableModules).map(([path, value]) => [basename(path), structuredClone(value)]));
  return rows as unknown as LiveTables;
}
