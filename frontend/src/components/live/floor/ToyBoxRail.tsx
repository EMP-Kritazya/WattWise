import { Bot, CircleDollarSign, Gauge } from "lucide-react";
import { useLive } from "@/data";
import { fmtKw, fmtUsd } from "@/lib/format";
import { NO_REAL_TARIFF, useRealTariff } from "@/lib/money";
import type { EscalationOption, LiveEscalationRow } from "@/types";

const INK = "#22223B";
const RED = "#EF476F";
const TRACK = "#E8E1EF";

const cardClass = "rounded-[22px] border-2 border-[#22223B] bg-white p-4 text-[#22223B] shadow-[0_5px_0_#22223B]";
const headingClass = "font-['Fredoka',sans-serif] text-[15px] font-bold tracking-tight";

function parseOptions(row: LiveEscalationRow | undefined): EscalationOption[] {
  if (!row) return [];
  try {
    const value = JSON.parse(row.options_json) as unknown;
    return Array.isArray(value) ? (value as EscalationOption[]) : [];
  } catch {
    return [];
  }
}

function pointOnGauge(value: number, max: number, radius: number) {
  const ratio = Math.max(0, Math.min(1, value / Math.max(1, max)));
  const angle = Math.PI * (1 - ratio);
  return { x: 130 + Math.cos(angle) * radius, y: 122 - Math.sin(angle) * radius };
}

function GaugeNeedle({ value, max, ghost = false }: { value: number; max: number; ghost?: boolean }) {
  const end = pointOnGauge(value, max, ghost ? 72 : 82);
  return (
    <line
      x1="130"
      y1="122"
      x2={end.x}
      y2={end.y}
      stroke={ghost ? "#9CA3AF" : INK}
      strokeWidth={ghost ? 5 : 7}
      strokeLinecap="round"
      strokeDasharray={ghost ? "7 8" : undefined}
    />
  );
}

function PeakGauge() {
  const ticks = useLive((state) => state.live_tick);
  const withTick = ticks.find((tick) => tick.lane === "with");
  const withoutTick = ticks.find((tick) => tick.lane === "without");
  const cap = withTick?.target_kw ?? withoutTick?.target_kw;
  const withKw = withTick?.block_avg_kw;
  const withoutKw = withoutTick?.block_avg_kw;
  const scale = Math.max(1, (cap ?? 40) * 1.3, withKw ?? 0, withoutKw ?? 0);
  const capStart = pointOnGauge(cap ?? scale, scale, 88);

  return (
    <section className={cardClass} aria-label="15-minute peak gauge">
      <div className="flex items-center gap-2">
        <Gauge className="size-4 text-[#2EC4B6]" />
        <h3 className={headingClass}>15-minute peak</h3>
      </div>
      <svg viewBox="0 0 260 156" className="mt-1 w-full" role="img" aria-label={`With WattWise ${fmtKw(withKw)}, without WattWise ${fmtKw(withoutKw)}, cap ${fmtKw(cap)}`}>
        <path d="M 38 122 A 92 92 0 0 1 222 122" fill="none" stroke={TRACK} strokeWidth="22" strokeLinecap="round" />
        <path
          d={`M ${capStart.x} ${capStart.y} A 88 88 0 0 1 218 122`}
          fill="none"
          stroke={RED}
          strokeWidth="18"
          strokeLinecap="round"
          opacity="0.82"
        />
        {withoutKw != null && <GaugeNeedle value={withoutKw} max={scale} ghost />}
        {withKw != null && <GaugeNeedle value={withKw} max={scale} />}
        <circle cx="130" cy="122" r="9" fill={INK} />
        <text x={Math.min(205, capStart.x + 7)} y={Math.max(21, capStart.y - 9)} fill={RED} fontSize="12" fontWeight="800">
          cap {cap == null ? "–" : cap.toFixed(1)}
        </text>
        <text x="130" y="151" fill={INK} fontSize="23" fontWeight="800" textAnchor="middle" fontFamily="Fredoka, sans-serif">
          {fmtKw(withKw)}
        </text>
      </svg>
      <div className="-mt-1 grid grid-cols-2 gap-2 text-xs font-bold">
        <div className="rounded-xl bg-[#DFF6F3] px-3 py-2 text-[#167D74]">
          <span className="block text-[10px] uppercase tracking-wide">With WattWise</span>
          {fmtKw(withKw)}
        </div>
        <div className="rounded-xl bg-[#F1F1F4] px-3 py-2 text-[#6B7280]">
          <span className="block text-[10px] uppercase tracking-wide">Ghost · without</span>
          {fmtKw(withoutKw)}
        </div>
      </div>
    </section>
  );
}

function DemandChargeCard() {
  const ticks = useLive((state) => state.live_tick);
  const escalations = useLive((state) => state.live_escalation);
  const escalation = escalations.at(-1);
  const options = parseOptions(escalation);
  const accept = options.find((option) => option.option_id === "accept_overrun");
  const chosen = options.find((option) => option.option_id === escalation?.chosen_option_id);
  const withTick = ticks.find((tick) => tick.lane === "with");
  const withoutTick = ticks.find((tick) => tick.lane === "without");
  const realTariff = useRealTariff();

  return (
    <section className={cardClass} aria-label="Demand charge comparison">
      <div className="flex items-center gap-2">
        <CircleDollarSign className="size-4 text-[#FFB703]" />
        <h3 className={headingClass}>This month&apos;s demand charge</h3>
      </div>
      <div className="mt-3 rounded-2xl bg-[#FCE4E1] px-4 py-3 text-[#B73E50]">
        <div className="text-[10px] font-extrabold uppercase tracking-wide">
          Without · {accept?.projected ? `new peak ${fmtKw(accept.projected.peak_kw)}` : fmtKw(withoutTick?.block_avg_kw)}
        </div>
        <div className="font-['Fredoka',sans-serif] text-2xl font-bold">
          {!realTariff ? NO_REAL_TARIFF : accept?.projected ? `+${fmtUsd(accept.projected.cost_delta_usd)}` : "Cost unavailable"}
        </div>
      </div>
      <div className="mt-2 rounded-2xl bg-[#DFF6F3] px-4 py-3 text-[#167D74]">
        <div className="text-[10px] font-extrabold uppercase tracking-wide">
          With · {chosen?.projected ? `held at ${fmtKw(chosen.projected.peak_kw)}` : fmtKw(withTick?.block_avg_kw)}
        </div>
        <div className="font-['Fredoka',sans-serif] text-2xl font-bold">
          {!realTariff
            ? NO_REAL_TARIFF
            : chosen?.projected
              ? chosen.projected.cost_delta_usd === 0
                ? "$0 extra"
                : `${fmtUsd(chosen.projected.cost_delta_usd)} extra`
              : "Cost unavailable"}
        </div>
      </div>
      {!escalation && <p className="mt-2 text-[11px] leading-snug text-[#6B687B]">No escalation cost is available yet, so only contract-provided kW is shown.</p>}
    </section>
  );
}

function claudeHeading(escalation: LiveEscalationRow | undefined, options: EscalationOption[]) {
  if (!escalation || escalation.status === "open") return "Claude is choosing…";
  if (escalation.status === "expired_default") return "Default option applied";
  const actionable = options.filter((option) => option.projected != null);
  const chosenIndex = actionable.findIndex((option) => option.option_id === escalation.chosen_option_id);
  return chosenIndex >= 0 ? `Claude chose ${chosenIndex + 1} of ${actionable.length}` : "Claude chose an option";
}

function ClaudeCard() {
  const escalations = useLive((state) => state.live_escalation);
  const escalation = escalations.at(-1);
  const options = parseOptions(escalation);
  const chosen = options.find((option) => option.option_id === escalation?.chosen_option_id);

  return (
    <section className="rounded-[22px] border-2 border-[#22223B] bg-[#69C9BF] p-4 text-[#22223B] shadow-[0_5px_0_#22223B]" aria-live="polite">
      <div className="flex items-center gap-2">
        <span className="flex size-8 items-center justify-center rounded-full bg-white/80">
          <Bot className="size-4" />
        </span>
        <h3 className="font-['Fredoka',sans-serif] text-base font-bold">{claudeHeading(escalation, options)}</h3>
      </div>
      <p className="mt-3 text-sm font-semibold leading-relaxed">
        {escalation?.rationale ?? chosen?.summary ?? "Watching the next 15-minute peak and staying inside the owner’s rules."}
      </p>
      {escalation && <p className="mt-3 text-[10px] font-extrabold uppercase tracking-[0.16em] opacity-70">{escalation.status.replace("_", " ")}</p>}
    </section>
  );
}

/** Judge-facing demo rail: three contract-backed cards, with no duplicate KPI or appliance-debug list. */
export function ToyBoxRail() {
  return (
    <aside
      className="flex min-h-0 flex-col gap-4 border-t-2 border-[#22223B] bg-[#FFF6E9] p-4 font-['Nunito',sans-serif] lg:border-t-0 lg:border-l-2"
      aria-label="Peak and WattWise outcome"
    >
      <PeakGauge />
      <DemandChargeCard />
      <ClaudeCard />
    </aside>
  );
}
