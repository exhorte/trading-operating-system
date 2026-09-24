import type { ReactNode } from "react";
import { buttonVariants } from "@/components/ui/button";

/**
 * shadcn/ui's Input look (2026-09-24 redesign), for native inputs and
 * selects alike — same field as the /journal and /analyse filters.
 */
export const inputClass =
  "h-9 w-full rounded-lg border border-input bg-input/30 px-3 text-sm text-foreground outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50";

/** The mock-up's « New Challenge »: filled mint, dark text. */
export const primaryButtonClass = buttonVariants({ size: "sm", className: "rounded-lg px-4" });

export const secondaryButtonClass = buttonVariants({ variant: "outline", size: "sm", className: "rounded-lg" });

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
    <label className="flex flex-col gap-1.5 text-xs">
      <span className="font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-xs leading-snug text-muted-foreground">{hint}</span>}
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
