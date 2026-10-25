import { beforeEach, describe, expect, it } from "vitest";
import wsStreamRaw from "@fixtures/ws/stream.jsonl?raw";
import rowsStreamRaw from "@fixtures/spacetime/rows_stream.jsonl?raw";
import backtestEventsRaw from "@fixtures/facade/run_backtest_on_progress.jsonl?raw";
import liveContextTable from "@fixtures/spacetime/tables/live_context.json";
import liveEscalationTable from "@fixtures/spacetime/tables/live_escalation.json";
import backtestPointTable from "@fixtures/spacetime/tables/backtest_point.json";
import backtestMonthTable from "@fixtures/spacetime/tables/backtest_month.json";
import wsBacktestPoint from "@fixtures/ws/backtest_point.json";
import type { BacktestPoint, BacktestResult, WsMessage } from "@/types";
import { backtestMonthOf, backtestMonthRow, backtestPointOf, backtestPointRow, contextRow, escalationRow } from "./rows";
import { emptyTables, useLive } from "./useLive";
import { normaliseRow } from "./spacetime";

const jsonl = <T,>(raw: string): T[] =>
  raw
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as T);

const ws = jsonl<WsMessage>(wsStreamRaw);

/** `*_json` columns parsed: JS writes 20 where Python writes 20.0, the same JSON number. */
const parsed = (rows: unknown): unknown =>
  (Array.isArray(rows) ? rows : [rows]).map((row) =>
    Object.fromEntries(
      Object.entries(row as Record<string, unknown>).map(([k, v]) => [k, k.endsWith("_json") && typeof v === "string" ? JSON.parse(v) : v]),
    ),
  );

describe("browser row builders equal the SpacetimeDB fixtures (same mapping as backend/live/rows.py)", () => {
  it("live_context and live_escalation", () => {
    const ctx = ws.filter((m) => m.type === "context").pop();
    const esc = ws.filter((m) => m.type === "escalation").pop();
    if (ctx?.type !== "context" || esc?.type !== "escalation") throw new Error("fixture stream changed");
    expect(parsed(contextRow(ctx.data))).toEqual(parsed(liveContextTable[0]));
    expect(parsed(escalationRow(esc.data))).toEqual(parsed(liveEscalationTable[0]));
  });

  it("backtest rows round-trip", () => {
    const events = jsonl<{ type: string; data: unknown }>(backtestEventsRaw);
    const points = events.filter((e) => e.type === "backtest_point").map((e) => backtestPointRow("run_0001", e.data as BacktestPoint));
    const months = events.filter((e) => e.type === "backtest_month").map((e) => backtestMonthRow("run_0001", e.data as BacktestResult));
    expect(parsed(points)).toEqual(parsed(backtestPointTable));
    expect(parsed(months)).toEqual(parsed(backtestMonthTable));
    expect(backtestPointOf(points[0])).toEqual(events.find((e) => e.type === "backtest_point")?.data);
    expect(backtestMonthOf(months[0])).toEqual(events.find((e) => e.type === "backtest_month")?.data);
  });
});

describe("useLive row store over /ws messages", () => {
  beforeEach(() => useLive.getState().replaceTables(emptyTables()));

  it("ticks become the fixture live rows (live_tick incl. demand_peaks_json, devices, comparison)", () => {
    useLive.getState().applyViewerMessages(ws);
    const frames = jsonl<Record<string, unknown>>(rowsStreamRaw);
    const last = frames[frames.length - 1] as { live_tick: unknown[]; live_device: unknown[]; live_comparison: unknown };
    const state = useLive.getState();
    expect(parsed([...state.live_tick].sort((a, b) => a.lane.localeCompare(b.lane)))).toEqual(
      parsed([...(last.live_tick as { lane: string }[])].sort((a, b) => a.lane.localeCompare(b.lane))),
    );
    expect(state.live_comparison).toEqual([last.live_comparison]);
    expect(state.tick_history).toHaveLength(240);
    expect(JSON.parse(state.live_tick[0].demand_peaks_json)[0].name).toBe("max_demand");
  });

  it("backtest messages fill backtest_point / backtest_month; a new run replaces the old one", () => {
    const point = wsBacktestPoint as unknown as WsMessage;
    useLive.getState().applyViewerMessages([point]);
    expect(useLive.getState().backtest_point).toHaveLength(1);
    if (point.type !== "backtest_point") throw new Error("fixture changed");
    useLive.getState().applyViewerMessages([{ ...point, run_id: "run_0002" }]);
    expect(useLive.getState().backtest_point.map((r) => r.key)).toEqual([`run_0002:${point.data.day}`]);
  });
});

describe("generated binding rows are normalised to section 5 rows", () => {
  it("camelCase keys, undefined options and bigint ids", () => {
    expect(normaliseRow({ onPeakMonthPeakKw: undefined, tickId: 5, id: 7n, demandPeaksJson: "[]" })).toEqual({
      on_peak_month_peak_kw: null,
      tick_id: 5,
      id: 7,
      demand_peaks_json: "[]",
    });
  });
});
