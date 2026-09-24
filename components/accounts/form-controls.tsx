import type { ReactNode } from "react";

/** Same field look as /journal and /analyse filters. */
export const inputClass =
  "w-full rounded border border-border bg-surface-elevated px-2 py-1 text-xs text-foreground disabled:opacity-50";

export const primaryButtonClass =
  "rounded border border-accent/50 bg-accent/10 px-3 py-1 text-xs font-medium text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent/10";

export const secondaryButtonClass =
  "rounded border border-border px-3 py-1 text-xs text-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted">{label}</span>
      {children}
      {hint && <span className="text-[11px] leading-snug text-muted">{hint}</span>}
    </label>
  );
}

/** « 23/09/2026 14:05 », local time — the trader reads their own clock. */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
