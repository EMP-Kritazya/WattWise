import { useEffect } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router";
import { ChartColumn, ChefHat, LayoutDashboard, Leaf } from "lucide-react";
import { ChatDrawer } from "@/components/ChatDrawer";
import { StatusBar } from "@/components/StatusBar";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { BuilderPage } from "@/pages/BuilderPage";
import { LivePage } from "@/pages/LivePage";
import { ProofPage } from "@/pages/ProofPage";
import { startLive } from "@/data";
import { useLive as useSim } from "@/data";
import { transport } from "@/transport";

const NAV = [
  { to: "/live", label: "Live", icon: LayoutDashboard },
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
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="flex-1">
            <Routes>
              <Route path="/" element={<Navigate to="/builder" replace />} />
              <Route path="/builder" element={<BuilderPage />} />
              <Route path="/live" element={<LivePage />} />
              <Route path="/proof" element={<ProofPage />} />
            </Routes>
          </main>
          <StatusBar className="border-t px-4 py-2 lg:hidden" />
        </div>
      </div>
    </BrowserRouter>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
        <Leaf className="size-5" />
      </span>
      <div className="leading-tight">
        <div className="text-base font-semibold tracking-tight">WattWise</div>
        <div className="text-[11px] text-muted-foreground">Keep the peak under the cap</div>
      </div>
    </div>
  );
}

function MockBadge() {
  return transport.kind === "mock" ? (
    <Badge variant="outline" className="border-amber-400/30 bg-amber-400/10 text-amber-300">
      Mock server: made-up numbers
    </Badge>
  ) : null;
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
    isActive && "bg-accent text-foreground",
  );

/** Large screens: brand, kitchen, navigation, and the connection status at the bottom. */
function Sidebar() {
  const kitchenName = useSim((s) => s.kitchen?.config.name);
  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-6 border-r bg-card/50 px-3 py-5 lg:flex">
      <div className="px-2">
        <Brand />
      </div>
      <div className="px-3">
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
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 lg:hidden">
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
