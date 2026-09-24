import type { ReactNode } from "react";
import { cn } from "cn";
import { Badge } from "./badge";

export type PillTone = "profit" | "loss" | "warning" | "info" | "accent" | "muted";

/**
 * Soft tinted pills, as on the reference mock-up (« +12.5% », « Funded »):
 * a translucent fill of the tone, no hard border — the colour carries the
 * meaning, discreetly. `accent` is the mint primary.
 */
const TONE_CLASSES: Record<PillTone, string> = {
  profit: "bg-profit/12 text-profit",
  loss: "bg-loss/12 text-loss",
  warning: "bg-warning/12 text-warning",
  info: "bg-info/12 text-info",
  accent: "bg-primary/12 text-primary",
  muted: "bg-muted text-muted-foreground ring-1 ring-border",
};

interface StatusPillProps {
  tone: PillTone;
  children: ReactNode;
  pulse?: boolean;
  className?: string;
}

export function StatusPill({ tone, children, pulse = false, className }: StatusPillProps) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 border-transparent px-2.5 py-0.5 text-[11px] font-medium",
        TONE_CLASSES[tone],
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full bg-current", pulse && "animate-pulse")} aria-hidden />
      {children}
    </Badge>
  );
}
