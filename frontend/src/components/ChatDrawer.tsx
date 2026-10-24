import { Bot } from "lucide-react";
import { AssistantPanel } from "@/components/AssistantPanel";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

/** The assistant in a slide-in drawer, for screens where it isn't docked. */
export function ChatDrawer({ className }: { className?: string }) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" className={className}>
          <Bot /> Ask WattWise
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full gap-0 sm:max-w-md">
        <SheetTitle className="sr-only">AI Energy Assistant</SheetTitle>
        <SheetDescription className="sr-only">Explains decisions and helps you change settings. It never controls equipment.</SheetDescription>
        <AssistantPanel bare className="h-full" />
      </SheetContent>
    </Sheet>
  );
}
