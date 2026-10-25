import { useMemo } from "react";
import { Bot, Cloud, Cpu, Network, Ticket, Users, Zap, type LucideIcon } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAgentLog } from "@/data";
import { cn } from "@/lib/utils";
import type { AgentLog } from "@/types";

// The agents talking (UI.md "Agent Network"): the Concierge in the centre, the Weather / Grid / Events agents around it,
// Claude and the WattWise engine as nodes (the contract's agent names). Each new agent_log row travels along its edge.

interface Node {
  id: string;
  label: string;
  sub: string;
  x: number;
  y: number;
  icon: LucideIcon;
  color: string;
}

const NODES: Node[] = [
  { id: "concierge", label: "Concierge", sub: "Fetch.ai uAgent · ASI:One", x: 300, y: 210, icon: Network, color: "#2EC4B6" },
  { id: "weather", label: "Weather", sub: "agent", x: 110, y: 80, icon: Cloud, color: "#A9D6F5" },
  { id: "grid", label: "Grid", sub: "agent · prices", x: 300, y: 50, icon: Zap, color: "#FFB703" },
  { id: "events", label: "Events", sub: "agent", x: 490, y: 80, icon: Ticket, color: "#FFC8DD" },
  { id: "claude", label: "Claude", sub: "explains · resolves escalations", x: 490, y: 350, icon: Bot, color: "#FFB4A2" },
  { id: "engine", label: "WattWise engine", sub: "decides · computes every number", x: 110, y: 350, icon: Cpu, color: "#C3CEF6" },
];
const NODE = Object.fromEntries(NODES.map((n) => [n.id, n]));
const EDGES: [string, string][] = [
  ["concierge", "weather"],
  ["concierge", "grid"],
  ["concierge", "events"],
  ["concierge", "claude"],
  ["engine", "claude"],
  ["concierge", "engine"],
];

/** Agents not in the fixed layout still show up, parked near the Concierge. */
const nodeFor = (id: string): Node => NODE[id] ?? { ...NODE.concierge, id, label: id, sub: "agent" };

export function AgentNetworkPage() {
  const log = useAgentLog();
  const recent = useMemo(() => log.slice(-50).reverse(), [log]);
  // The last few messages animate along their edges; keys change with the log so each one plays once.
  const flying = log.slice(-6).map((m, i) => ({ m, key: `${log.length - 6 + i}:${m.ts_real}` }));
  const active = new Set<string>(log.slice(-6).flatMap((m) => [m.from_agent, m.to_agent]));

  return (
    <div className="mx-auto grid max-w-7xl gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_380px] xl:p-6">
      <Card className="gap-2 py-4">
        <CardHeader className="px-4">
          <CardTitle className="flex items-center gap-2">
            <Users className="size-4" /> Agent Network
          </CardTitle>
          <CardDescription>
            Agents sense the world, the engine decides and does the math, Claude judges the hard cases and talks to the owner.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-4">
          <div className="rounded-[18px] border-2 border-[#22223B] bg-[#FFF6E9] p-2">
          <svg viewBox="0 0 600 450" className="mx-auto h-auto w-full max-w-xl" role="img" aria-label="Agent network graph">
            {EDGES.map(([a, b]) => {
              const na = nodeFor(a);
              const nb = nodeFor(b);
              return <line key={`${a}-${b}`} x1={na.x} y1={na.y} x2={nb.x} y2={nb.y} stroke="#22223B" strokeOpacity={0.25} strokeWidth={2} strokeDasharray="7 6" />;
            })}
            {flying.map(({ m, key }) => {
              const a = nodeFor(m.from_agent);
              const b = nodeFor(m.to_agent);
              return (
                <circle key={key} r={6} fill={a.color} style={{ filter: `drop-shadow(0 0 6px ${a.color})` }}>
                  <animate attributeName="cx" from={a.x} to={b.x} dur="1.2s" fill="freeze" />
                  <animate attributeName="cy" from={a.y} to={b.y} dur="1.2s" fill="freeze" />
                  <animate attributeName="opacity" values="1;1;0" dur="1.6s" fill="freeze" />
                </circle>
              );
            })}
            {NODES.map((n) => {
              const Icon = n.icon;
              const on = active.has(n.id);
              return (
                <g key={n.id} transform={`translate(${n.x}, ${n.y})`}>
                  <circle r={n.id === "concierge" ? 38 : 30} fill={n.color} stroke="#22223B" strokeWidth={on ? 4 : 2.5} />
                  <foreignObject x={-12} y={-12} width={24} height={24}>
                    <Icon className="size-6 text-[#22223B]" />
                  </foreignObject>
                  <text y={n.id === "concierge" ? 56 : 48} textAnchor="middle" className="fill-foreground text-[13px] font-semibold">
                    {n.label}
                  </text>
                  <text y={n.id === "concierge" ? 71 : 63} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                    {n.sub}
                  </text>
                </g>
              );
            })}
          </svg>
          </div>
        </CardContent>
      </Card>

      <Card className="gap-2 py-4">
        <CardHeader className="px-4">
          <CardTitle>Messages</CardTitle>
          <CardDescription>Last 50, newest first</CardDescription>
        </CardHeader>
        <CardContent className="flex max-h-[560px] flex-col gap-1.5 overflow-y-auto px-4">
          {!recent.length && <p className="text-sm text-muted-foreground">No agent messages yet. Build a kitchen and press Play.</p>}
          {recent.map((m, i) => (
            <MessageRow key={`${m.ts_real}-${i}`} m={m} />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function MessageRow({ m }: { m: AgentLog }) {
  const from = nodeFor(m.from_agent);
  const to = nodeFor(m.to_agent);
  return (
    <div className="rounded-2xl border-2 border-[#22223B] bg-[#FFF6E9] px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5">
        <b style={{ color: from.color }}>{from.label}</b>
        <span className="text-muted-foreground">→</span>
        <b style={{ color: to.color }}>{to.label}</b>
        <span className={cn("ml-auto rounded-full border border-[#22223B]/20 bg-secondary px-2 text-[10px] font-bold uppercase text-muted-foreground")}>{m.kind}</span>
      </div>
      <div className="mt-0.5 text-muted-foreground">{m.summary}</div>
    </div>
  );
}
