import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "cn";

export type MetricTone = "success" | "warning" | "destructive";

const TONE_CLASS: Record<MetricTone, string> = {
  success: "text-panel-success",
  warning: "text-panel-warning",
  destructive: "text-panel-destructive",
};

const BAR_CLASS: Record<MetricTone | "neutral", string> = {
  success: "bg-panel-success",
  warning: "bg-panel-warning",
  destructive: "bg-panel-destructive",
  neutral: "bg-panel-foreground/80",
};

/**
 * Compact dark strip: a large icon, the headline figure, its label on the
 * right. It carries THE number of the screen (equity, `n/9` gates…).
 *
 * It wraps: when the label and the figure do not fit on one row (a phone, a
 * long label) the label drops to its own row instead of squeezing the figure
 * — « $10,15… » is not a headline. The figure only truncates when it is wider
 * than the whole strip.
 */
export function HighlightBar({
  icon: Icon,
  value,
  label,
  aside,
  className,
}: {
  icon: LucideIcon;
  value: ReactNode;
  label: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl bg-panel px-5 py-4 text-panel-foreground shadow-sm",
        className
      )}
    >
      <Icon className="size-8 shrink-0 stroke-[1.5]" aria-hidden="true" />
      <p
        className="max-w-full min-w-0 truncate text-2xl font-semibold tracking-tight tabular-nums"
        title={typeof value === "string" ? value : undefined}
      >
        {value}
      </p>
      <div className="ml-auto flex max-w-full flex-col items-end gap-1.5 text-right">
        <span className="text-sm text-panel-muted">{label}</span>
        {aside}
      </div>
    </div>
  );
}

/** Dark panel stacking metrics separated by hairlines. Dark in both themes. */
export function MetricPanel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "flex flex-col divide-y divide-panel-border overflow-hidden rounded-xl bg-panel text-panel-foreground shadow-sm",
        className
      )}
    >
      {children}
    </div>
  );
}

export function MetricPanelItem({
  label,
  value,
  unit,
  hint,
  icon: Icon,
  solidIcon = false,
  tone,
  progress,
  untrusted = false,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  icon: LucideIcon;
  /** The pale-mint chip that picks out ONE metric of the panel. */
  solidIcon?: boolean;
  tone?: MetricTone;
  /** 0–100: a thin bar under the figure — how much of a limit is consumed. Coloured like `tone`. */
  progress?: number;
  /** Realtime data can no longer be trusted: dim the figure. */
  untrusted?: boolean;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 p-6 transition-opacity", untrusted && "opacity-60")}>
      <div className="min-w-0">
        <p className="text-sm text-panel-muted">{label}</p>
        <p
          className={cn(
            "mt-2 text-2xl font-semibold tracking-tight tabular-nums sm:text-[28px] sm:leading-9",
            tone && TONE_CLASS[tone]
          )}
        >
          {value}
          {unit && <span className="ml-1.5 text-base font-medium text-panel-foreground">{unit}</span>}
        </p>
        {hint && <p className="mt-1.5 text-xs text-panel-muted">{hint}</p>}
        {progress !== undefined && (
          <div className="mt-3 h-1.5 w-full min-w-40 overflow-hidden rounded-full bg-white/10" aria-hidden="true">
            <div
              className={cn("h-full rounded-full transition-[width] duration-300", BAR_CLASS[tone ?? "neutral"])}
              style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
            />
          </div>
        )}
      </div>
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-full",
          solidIcon ? "bg-panel-highlight text-panel-highlight-foreground" : "bg-white/10 text-panel-foreground"
        )}
      >
        <Icon className="size-4" aria-hidden="true" />
      </span>
    </div>
  );
}

/** Compact key / value list, at the bottom of a `MetricPanel`. */
export function MetricPanelList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-4 p-6 text-sm">
      {items.map((item) => (
        <div key={item.label} className="flex min-w-0 flex-col gap-1">
          <dt className="text-xs text-panel-muted">{item.label}</dt>
          <dd className="truncate font-medium tabular-nums">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
