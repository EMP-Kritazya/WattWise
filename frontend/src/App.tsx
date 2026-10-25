import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router";
import { ChefHat, LayoutDashboard, Leaf, Microscope, MonitorPlay } from "lucide-react";
import { ChatDrawer } from "@/components/ChatDrawer";
import { SectionTabs, type SectionTab } from "@/components/SectionTabs";
import { StatusBar } from "@/components/StatusBar";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { BuilderPage } from "@/pages/BuilderPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { EvalLabPage } from "@/pages/EvalLabPage";
import { LivePage } from "@/pages/LivePage";
import { SimHostPage } from "@/pages/SimHostPage";
import { HtmlOverlays } from "@/components/live/floor/HtmlOverlay";
import { startLive } from "@/data";
import { useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";

// The three top tabs. Dashboard holds two screens, switched by sub-tabs.
const NAV = [
  { to: "/live", label: "Live Simulation", icon: MonitorPlay },
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/eval", label: "Evaluation Lab", icon: Microscope },
];
const DASHBOARD_TABS: SectionTab[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/dashboard/builder", label: "Kitchen Builder", icon: ChefHat },
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
      <HtmlOverlays />
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Navigate to="/live" replace />} />
          {/* Rendered by Shell, which keeps it mounted (see there). */}
          <Route path="/live" element={null} />
          <Route path="/dashboard" element={<SectionTabs tabs={DASHBOARD_TABS} label="Dashboard sections" />}>
            <Route index element={<DashboardPage />} />
            <Route path="builder" element={<BuilderPage />} />
          </Route>
          <Route path="/eval" element={<EvalLabPage />} />
          <Route path="/sim" element={<SimHostPage />} />
          {/* Old addresses still work. */}
          <Route path="/builder" element={<Navigate to="/dashboard/builder" replace />} />
          <Route path="/proof/*" element={<Navigate to="/live" replace />} />
          <Route path="/agents" element={<Navigate to="/live" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

/** The top bar with the three tabs above every screen. Claude resolves escalations itself, so no decision dialog. */
function Shell() {
  const onLive = useLocation().pathname === "/live";
  // Keep the floor mounted and pause its render loop on other tabs so returning to Live is instant.
  const [liveVisited, setLiveVisited] = useState(onLive);
  useEffect(() => {
    if (onLive) setLiveVisited(true);
  }, [onLive]);
  return (
    <div className="flex min-h-screen flex-col bg-transparent">
      <TopBar />
      <main className="min-w-0 flex-1">
        {liveVisited && (
          <div hidden={!onLive}>
            <LivePage active={onLive} />
          </div>
        )}
        <Outlet />
      </main>
    </div>
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
    "flex items-center gap-2 rounded-xl border-2 border-transparent px-3 py-2 text-sm font-extrabold whitespace-nowrap text-muted-foreground transition-all hover:bg-accent hover:text-foreground",
    isActive && "border-[#22223B] bg-primary text-[#22223B] shadow-[0_3px_0_#22223B]",
  );

/** Brand, the three tabs, kitchen and connection status, and the assistant, at every width. */
function TopBar() {
  const kitchenName = useSim((s) => s.kitchen?.config.name);
  // Its height as `--topbar-h`, so a screen can fill exactly the rest of the window (Live Simulation).
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--topbar-h", `${el.offsetHeight}px`));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <header ref={ref} className="sticky top-0 z-30 flex flex-wrap items-center gap-x-5 gap-y-2 border-b-2 border-[#22223B] bg-[#FFF1E2]/95 px-4 py-3 backdrop-blur sm:px-6">
      <Brand />
      <nav aria-label="Main" className="order-last flex w-full gap-1 overflow-x-auto lg:order-none lg:w-auto">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={navClass}>
            <Icon className="size-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <MockBadge />
        <div className="hidden text-right leading-tight sm:block">
          <div className="max-w-40 truncate text-sm font-bold">{kitchenName ?? "No kitchen yet"}</div>
          <StatusBar className="justify-end" />
        </div>
        <ChatDrawer />
      </div>
    </header>
  );
}
