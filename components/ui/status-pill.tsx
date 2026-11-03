import type { ReactNode } from "react";
import { cn } from "cn";
import { Badge } from "./badge";

export type PillTone = "profit" | "loss" | "warning" | "info" | "accent" | "muted";

/**
 * Soft tinted badges with a dot: the state is carried by the dot AND the
 * words, never by colour alone. `accent` is the strong, near-black badge;
 * the others are the semantic colours (success, error, warning, info).
 */
const TONE_CLASSES: Record<PillTone, string> = {
  profit: "border-success/20 bg-success/10 text-success",
  loss: "border-destructive/20 bg-destructive/10 text-destructive",
  warning: "border-warning/25 bg-warning/10 text-warning",
  info: "border-info/25 bg-info/10 text-info",
  accent: "border-transparent bg-primary text-primary-foreground",
  muted: "bg-muted text-muted-foreground",
};

/** The same tones, lightened so they stay readable on the dark metric panel. */
const PANEL_TONE_CLASSES: Record<PillTone, string> = {
  profit: "border-panel-success/30 bg-panel-success/15 text-panel-success",
  loss: "border-panel-destructive/30 bg-panel-destructive/15 text-panel-destructive",
  warning: "border-panel-warning/30 bg-panel-warning/15 text-panel-warning",
  info: "border-panel-border bg-white/5 text-panel-muted",
  accent: "border-transparent bg-panel-highlight text-panel-highlight-foreground",
  muted: "border-panel-border bg-transparent text-panel-muted",
};

interface StatusPillProps {
  tone: PillTone;
  children: ReactNode;
  pulse?: boolean;
  /** On a `bg-panel` surface: switches to the panel-* tokens. */
  onPanel?: boolean;
  className?: string;
}

export function StatusPill({ tone, children, pulse = false, onPanel = false, className }: StatusPillProps) {
  return (
    <Badge
      variant="outline"
      className={cn("text-[0.6875rem]", onPanel ? PANEL_TONE_CLASSES[tone] : TONE_CLASSES[tone], className)}
    >
      <span className={cn("size-1.5 rounded-full bg-current", pulse && "animate-pulse")} aria-hidden />
      {children}
    </Badge>
  );
}
