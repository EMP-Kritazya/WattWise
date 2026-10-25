import type { ReactNode } from "react";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * "No data yet": shown wherever the backend has nothing real to give (an engine feature not built yet, no agent context,
 * no eval results). It says what is missing and why, and never stands in for numbers.
 */
export function NoData({ title, children, className }: { title: string; children?: ReactNode; className?: string }) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-3 rounded-[22px] border-2 border-dashed border-[#22223B]/50 bg-white/70 px-4 py-3 text-sm text-[#22223B]",
        className,
      )}
    >
      <Inbox className="mt-0.5 size-4 shrink-0 text-[#6B687B]" />
      <div className="min-w-0">
        <div className="font-bold">{title}</div>
        {children && <div className="mt-0.5 text-xs leading-relaxed text-[#6B687B]">{children}</div>}
      </div>
    </div>
  );
}
