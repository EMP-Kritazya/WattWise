import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-extrabold transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:ring-ring/40 focus-visible:ring-[4px] aria-invalid:ring-destructive/20 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default: "border-2 border-[#22223B] bg-primary text-primary-foreground shadow-[0_3px_0_#22223B] hover:-translate-y-0.5 hover:bg-[#51D0C5]",
        destructive: "border-2 border-[#22223B] bg-destructive text-white shadow-[0_3px_0_#22223B] hover:-translate-y-0.5 hover:bg-destructive/90 focus-visible:ring-destructive/20",
        outline: "border-2 border-[#22223B] bg-white text-[#22223B] shadow-[0_3px_0_#22223B] hover:-translate-y-0.5 hover:bg-accent",
        secondary: "border-2 border-[#22223B] bg-secondary text-secondary-foreground shadow-[0_3px_0_#22223B] hover:-translate-y-0.5 hover:bg-[#FFE7D1]",
        ghost: "border-2 border-transparent shadow-none hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-xl gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-11 rounded-xl px-6 has-[>svg]:px-4",
        icon: "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : "button";

  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export { Button, buttonVariants };
