import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bot, Clock, Gauge, Send, Snowflake, Users, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn, errorMessage } from "@/lib/utils";
import { useSim } from "@/store/sim";
import { transport } from "@/transport";

const SUGGESTIONS: { icon: LucideIcon; text: string }[] = [
  { icon: Clock, text: "Why did you delay the dishwasher?" },
  { icon: Users, text: "We have a 40-person party at 7. What happens?" },
  { icon: Gauge, text: "How close are we to this month's peak?" },
  { icon: Snowflake, text: "Never touch the walk-in cooler." },
];

/** Chat with the assistant. It explains and helps configure; it never controls equipment or computes numbers. */
export function AssistantPanel({ className, bare }: { className?: string; bare?: boolean }) {
  const chat = useSim((s) => s.chat);
  const addOwnerChat = useSim((s) => s.addOwnerChat);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Block body on purpose: newer Chromium returns a Promise from scrollIntoView, and an effect must not return one.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [chat]);

  async function send(text: string) {
    const message = text.trim();
    if (!message) return;
    setDraft("");
    setError(null);
    addOwnerChat(message);
    try {
      // The reply streams back over /ws as chat_delta / chat_done.
      await transport.chat(message);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    send(draft);
  }

  return (
    <section className={cn("flex min-h-0 flex-col", !bare && "rounded-xl border bg-card", className)}>
      <header className="flex items-center gap-3 border-b px-4 py-3">
        <span className="flex size-9 items-center justify-center rounded-xl bg-importance-flexible/15 text-importance-flexible">
          <Bot className="size-5" />
        </span>
        <div>
          <div className="font-semibold">AI Energy Assistant</div>
          <div className="text-xs text-muted-foreground">Explains decisions · never controls equipment</div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        <AssistantBubble text="Hi! Ask me why WattWise did something, or tell me about a rush coming up. Every number I give comes from the engine." />
        {chat.map((m) =>
          m.role === "owner" ? (
            <div key={m.id} className="max-w-[85%] self-end rounded-2xl rounded-br-md bg-[oklch(0.55_0.17_262)] px-3 py-2 text-sm text-white">
              {m.text}
            </div>
          ) : (
            <AssistantBubble key={m.id} text={m.text} streaming={!m.done} />
          ),
        )}
        {/* Phase 2: Confirm / Cancel cards for AI proposals ("Apply this change"). Blocked on a `proposal` message in CONTRACTS.md. */}
        <div ref={bottomRef} />
      </div>

      <div className="border-t px-4 pt-3">
        <div className="text-xs text-muted-foreground">You can also try</div>
        <div className="mt-2 flex flex-col gap-1.5">
          {SUGGESTIONS.map(({ icon: Icon, text }) => (
            <button
              key={text}
              type="button"
              onClick={() => send(text)}
              className="flex items-center gap-2 rounded-lg border bg-secondary/40 px-3 py-2 text-left text-xs transition-colors hover:bg-secondary"
            >
              <Icon className="size-3.5 shrink-0 text-importance-flexible" />
              {text}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="px-4 pt-2 text-xs text-destructive">{error}</p>}
      <form onSubmit={submit} className="flex gap-2 p-4">
        <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask anything…" />
        <Button type="submit" size="icon" aria-label="Send">
          <Send />
        </Button>
      </form>
    </section>
  );
}

function AssistantBubble({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div className="flex max-w-[92%] items-start gap-2 self-start">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg bg-importance-flexible/15 text-importance-flexible">
        <Bot className="size-3.5" />
      </span>
      <div className="rounded-2xl rounded-tl-md bg-secondary px-3 py-2 text-sm leading-relaxed">
        {text}
        {streaming && <span className="animate-pulse">▍</span>}
      </div>
    </div>
  );
}
