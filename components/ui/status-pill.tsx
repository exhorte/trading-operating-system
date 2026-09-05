import type { ReactNode } from "react";

export type PillTone = "profit" | "loss" | "warning" | "info" | "accent" | "muted";

const TONE_CLASSES: Record<PillTone, string> = {
  profit: "border-profit/40 bg-profit/10 text-profit",
  loss: "border-loss/40 bg-loss/10 text-loss",
  warning: "border-warning/40 bg-warning/10 text-warning",
  info: "border-info/40 bg-info/10 text-info",
  accent: "border-accent/40 bg-accent/10 text-accent",
  muted: "border-border-strong bg-surface-elevated text-muted",
};

interface StatusPillProps {
  tone: PillTone;
  children: ReactNode;
  pulse?: boolean;
}

export function StatusPill({ tone, children, pulse = false }: StatusPillProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONE_CLASSES[tone]}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full bg-current ${pulse ? "animate-pulse" : ""}`}
        aria-hidden
      />
      {children}
    </span>
  );
}
