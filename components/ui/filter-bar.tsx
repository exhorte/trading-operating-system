import type { ReactNode } from "react";
import { cn } from "cn";

/**
 * The filters of a list screen (/journal, /analyse): a quiet bordered strip of
 * labelled fields. The controls themselves use `filterFieldClass`
 * (components/ui/input.tsx), so a filter and a form field share one look.
 */
export function FilterBar({
  children,
  label = "Filtres",
  className,
}: {
  children: ReactNode;
  /** Accessible name of the group. */
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn("flex flex-wrap items-end gap-x-4 gap-y-3 rounded-xl border bg-card p-4 shadow-xs", className)}
    >
      {children}
    </div>
  );
}

/** A label above its control — the `<label>` wraps the control, so the association is the markup's. */
export function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[13px] text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
