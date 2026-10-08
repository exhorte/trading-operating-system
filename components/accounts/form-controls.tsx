import type { ReactNode } from "react";
import { buttonVariants } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/input";

/**
 * The same field as `<Input>`, for native inputs and selects alike (and the
 * /journal and /analyse filters) — one look for every field of the app.
 */
export const inputClass = fieldClass;

/** The action button: the near-black one. */
export const primaryButtonClass = buttonVariants({ size: "default" });

export const secondaryButtonClass = buttonVariants({ variant: "outline", size: "sm" });

/** A labelled field: the `<label>` wraps its control, so the association is the markup's. */
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
    <label className="flex flex-col gap-2">
      <span className="text-[13px] text-muted-foreground">{label}</span>
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
