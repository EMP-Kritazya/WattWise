import { useEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtUsd } from "@/lib/format";
import { LANE_COLOR } from "@/lib/theme";
import type { ProofExtras } from "@/types";

const DURATION_MS = 15_000;
const W = 1000;
const H = 180;
const TIMER_COLOR = "var(--muted-foreground)";
const dateFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", weekday: "short", month: "short", day: "numeric", hour: "numeric" });
const monthFmt = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "long", year: "numeric" });

/**
 * "Replay month" (UI.md): plays a cached month in ~15 s, hour by hour, with the three running bills ticking.
 * The bills are the engine's running totals for each hour; the browser only picks which hour to show.
 */
export function ReplayMonth({ replay, savedVsWithout, savedVsTimer }: { replay: ProofExtras["replay"]; savedVsWithout?: number; savedVsTimer?: number }) {
  const steps = replay.steps;
  const [progress, setProgress] = useState(0);
  const [playing, setPlaying] = useState(false);
  const frame = useRef<number>(0);
  const startedAt = useRef(0);

  useEffect(() => {
    if (!playing) return;
    startedAt.current = performance.now() - progress * DURATION_MS;
    const tick = (now: number) => {
      // A frame's timestamp can predate the performance.now() taken at start, so clamp at 0 too.
      const p = Math.min(1, Math.max(0, (now - startedAt.current) / DURATION_MS));
      setProgress(p);
      if (p < 1) frame.current = requestAnimationFrame(tick);
      else setPlaying(false);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
    // progress is read once when play starts; it must not restart the loop every frame.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  const idx = Math.max(0, Math.min(steps.length - 1, Math.floor(progress * (steps.length - 1))));
  const step = steps[idx];
  const done = progress >= 1;
  // Visual scale only (line height), never displayed.
  const top = Math.max(...steps.map((s) => s.without_kw)) * 1.05;
  const line = (key: "without_kw" | "timer_kw" | "with_kw") =>
    steps.map((s, i) => `${((i / (steps.length - 1)) * W).toFixed(1)},${(H - (s[key] / top) * H).toFixed(1)}`).join(" ");

  const toggle = () => {
    if (done) setProgress(0);
    setPlaying((p) => !p);
  };

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="flex flex-row flex-wrap items-start gap-3 px-4">
        <div className="min-w-0 flex-1">
          <CardTitle>Replay month · {monthFmt.format(new Date(`${replay.month}-01T00:00:00Z`))}</CardTitle>
          <CardDescription>The whole month in 15 seconds, one hour at a time. Each bill grows as energy is used and as its peak rises.</CardDescription>
        </div>
        <div className="flex gap-2">
          <Button onClick={toggle} size="sm">
            {playing ? <Pause /> : <Play />}
            {playing ? "Pause" : done ? "Replay again" : progress > 0 ? "Resume" : "Replay month"}
          </Button>
          {progress > 0 && !playing && !done && (
            <Button variant="ghost" size="sm" onClick={() => setProgress(0)} aria-label="Back to the start">
              <RotateCcw />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-4">
        <div className="grid gap-3 sm:grid-cols-3" aria-live="off">
          <Counter label="Without WattWise" color={LANE_COLOR.without} value={step.without_usd} />
          <Counter label="Timer schedule" color={TIMER_COLOR} value={step.timer_usd} />
          <Counter label="With WattWise" color={LANE_COLOR.with} value={step.with_usd} />
        </div>
        <div className="relative rounded-lg border bg-secondary/30 p-2">
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-40 w-full" role="img" aria-label="Load per hour during the replayed month">
            <defs>
              <clipPath id="replay-reveal">
                <rect x={0} y={0} width={Math.max(1, progress * W)} height={H} />
              </clipPath>
            </defs>
            <g opacity={0.12}>
              <polyline points={line("without_kw")} fill="none" stroke={LANE_COLOR.without} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
            </g>
            <g clipPath="url(#replay-reveal)">
              <polyline points={line("without_kw")} fill="none" stroke={LANE_COLOR.without} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
              <polyline points={line("timer_kw")} fill="none" stroke={TIMER_COLOR} strokeWidth={1} strokeOpacity={0.7} vectorEffect="non-scaling-stroke" />
              <polyline points={line("with_kw")} fill="none" stroke={LANE_COLOR.with} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
            </g>
            <line x1={progress * W} x2={progress * W} y1={0} y2={H} stroke="var(--foreground)" strokeOpacity={0.5} vectorEffect="non-scaling-stroke" />
          </svg>
          <div className="mt-1 flex justify-between text-xs text-muted-foreground tabular-nums">
            <span>{dateFmt.format(new Date(step.ts))}</span>
            <span>kW per hour · Without · Timer · With</span>
          </div>
        </div>
        {done && savedVsWithout != null && (
          <p className="text-sm">
            This month WattWise saved <b className="text-lane-with tabular-nums">{fmtUsd(savedVsWithout)}</b> against doing nothing
            {savedVsTimer != null && (
              <>
                {" "}
                and <b className="tabular-nums">{fmtUsd(savedVsTimer)}</b> against the best timer schedule
              </>
            )}
            .
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Counter({ label, color, value }: { label: string; color: string; value: number }) {
  return (
    <div className="rounded-lg border px-3 py-2" style={{ borderColor: `color-mix(in oklch, ${color} 40%, transparent)` }}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular-nums" style={{ color }}>
        {fmtUsd(value)}
      </div>
    </div>
  );
}
