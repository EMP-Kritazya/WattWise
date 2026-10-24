import { useEffect } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router";
import { ChartColumn, ChefHat, LayoutDashboard, Leaf, Network } from "lucide-react";
import { ChatDrawer } from "@/components/ChatDrawer";
import { EscalationDialog } from "@/components/live/EscalationDialog";
import { StatusBar } from "@/components/StatusBar";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { AgentNetworkPage } from "@/pages/AgentNetworkPage";
import { BuilderPage } from "@/pages/BuilderPage";
import { LivePage } from "@/pages/LivePage";
import { ProofPage } from "@/pages/ProofPage";
import { SimHostPage } from "@/pages/SimHostPage";
import { startLive } from "@/data";
import { useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";

const NAV = [
  { to: "/live", label: "Live", icon: LayoutDashboard },
  { to: "/agents", label: "Agent Network", icon: Network },
  { to: "/builder", label: "Kitchen Builder", icon: ChefHat },
  { to: "/proof", label: "Proof", icon: ChartColumn },
];

export default function App() {
  const connection = useSim((s) => s.connection);

  useEffect(() => startLive(), []);

  // The socket doesn't replay state on connect (contract gap), so catch up over REST after every (re)connect.
  useEffect(() => {
    if (connection !== "open") return;
    const { setKitchen, upsertDecisions } = useSim.getState();
    transport.getKitchen().then(setKitchen, () => {});
    transport.listDecisions().then(upsertDecisions, () => {});
  }, [connection]);

  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-transparent">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="flex-1">
            <Routes>
              <Route path="/" element={<Navigate to="/builder" replace />} />
              <Route path="/builder" element={<BuilderPage />} />
              <Route path="/live" element={<LivePage />} />
              <Route path="/agents" element={<AgentNetworkPage />} />
              <Route path="/proof" element={<ProofPage />} />
              <Route path="/sim" element={<SimHostPage />} />
            </Routes>
            {/* On every screen: a waiting escalation pauses the clock, so the owner must always see it. */}
            <EscalationDialog />
          </main>
          <StatusBar className="border-t-2 border-[#22223B] bg-[#FFF1E2] px-4 py-2 lg:hidden" />
        </div>
      </div>
    </BrowserRouter>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-10 items-center justify-center rounded-xl border-2 border-[#22223B] bg-primary text-primary-foreground shadow-[0_3px_0_#22223B]">
        <Leaf className="size-5" />
      </span>
      <div className="leading-tight">
        <div className="font-['Fredoka',sans-serif] text-lg font-bold tracking-tight">WattWise</div>
        <div className="text-[11px] text-muted-foreground">Keep the peak under the cap</div>
      </div>
    </div>
  );
}

function MockBadge() {
  return transport.kind === "mock" ? (
    <Badge variant="outline" className="border-[#22223B] bg-[#FFF0BA] text-[#704A00]">
      {import.meta.env.VITE_MOCKS === "1" ? "Fixture mode · fake data" : "Legacy mock · made-up numbers"}
    </Badge>
  ) : null;
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-2.5 rounded-xl border-2 border-transparent px-3 py-2 text-sm font-extrabold text-muted-foreground transition-all hover:bg-accent hover:text-foreground",
    isActive && "border-[#22223B] bg-primary text-[#22223B] shadow-[0_3px_0_#22223B]",
  );

/** Large screens: brand, kitchen, navigation, and the connection status at the bottom. */
function Sidebar() {
  const kitchenName = useSim((s) => s.kitchen?.config.name);
  return (
    <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-6 border-r-2 border-[#22223B] bg-[#FFF1E2]/95 px-3 py-5 lg:flex">
      <div className="px-2">
        <Brand />
      </div>
      <div className="rounded-2xl border-2 border-[#22223B] bg-white px-3 py-2.5 shadow-[0_3px_0_#22223B]">
        <div className="text-[11px] tracking-wide text-muted-foreground uppercase">Kitchen</div>
        <div className="mt-0.5 truncate font-medium">{kitchenName ?? "Not built yet"}</div>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={navClass}>
            <Icon className="size-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-3 px-2">
        <MockBadge />
        <StatusBar className="flex-col items-start gap-y-0.5" />
      </div>
    </aside>
  );
}

/** Small screens: everything from the sidebar in one row. */
function TopBar() {
  return (
    <header className="sticky top-0 z-30 flex flex-wrap items-center gap-x-4 gap-y-2 border-b-2 border-[#22223B] bg-[#FFF1E2]/95 px-4 py-3 backdrop-blur lg:hidden">
      <Brand />
      <nav className="flex gap-1">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={navClass}>
            <Icon className="size-4" />
            <span className="hidden sm:inline">{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2">
        <MockBadge />
        <ChatDrawer />
      </div>
    </header>
  );
}
