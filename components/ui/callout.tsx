import type { ReactNode } from "react";
import { Info, TriangleAlert } from "lucide-react";
import { cn } from "cn";

/**
 * A note: « Important » (info) or a warning. This is where a screen states
 * what its figures do NOT mean — « this verdict only covers what goes through
 * this system » — so it is read where the verdict is read.
 */
export function Callout({
  title,
  children,
  variant = "info",
  className,
}: {
  title: string;
  children: ReactNode;
  variant?: "info" | "warning";
  className?: string;
}) {
  const Icon = variant === "warning" ? TriangleAlert : Info;
  return (
    <div
      role={variant === "warning" ? "alert" : "note"}
      className={cn(
        "rounded-xl border p-4 sm:px-5",
        variant === "warning" && "border-warning/30 bg-warning/5",
        className
      )}
    >
      <p className="flex items-center gap-2 text-sm font-semibold">
        <Icon className={cn("size-4 shrink-0", variant === "warning" && "text-warning")} aria-hidden="true" />
        {title}
      </p>
      <div className="mt-1.5 pl-6 text-sm text-muted-foreground">{children}</div>
    </div>
  );
}
