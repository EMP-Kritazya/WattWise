import { NavLink, Outlet } from "react-router";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SectionTab {
  to: string;
  label: string;
  icon: LucideIcon;
}

/** A top-level tab with more than one screen: a row of sub-tabs, then the chosen screen. */
export function SectionTabs({ tabs, label }: { tabs: SectionTab[]; label: string }) {
  return (
    <div className="flex flex-col">
      <nav aria-label={label} className="flex flex-wrap gap-2 px-4 pt-4 sm:px-6">
        {tabs.map(({ to, label, icon: Icon }, i) => (
          <NavLink
            key={to}
            to={to}
            end={i === 0}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 rounded-full border-2 border-[#22223B] px-3.5 py-1.5 text-sm font-extrabold transition-all",
                isActive ? "bg-[#22223B] text-white" : "bg-white text-[#22223B] shadow-[0_2px_0_#22223B] hover:bg-accent",
              )
            }
          >
            <Icon className="size-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
