import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "cn";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

export type KpiTone = "default" | "profit" | "loss" | "warning";

const VALUE_TONE: Record<KpiTone, string> = {
  default: "text-foreground",
  profit: "text-profit",
  loss: "text-loss",
  warning: "text-warning",
};

const BAR_TONE: Record<KpiTone, { track: string; bar: string }> = {
  default: { track: "bg-primary/15", bar: "bg-primary" },
  profit: { track: "bg-primary/15", bar: "bg-primary" },
  warning: { track: "bg-warning/15", bar: "bg-warning" },
  loss: { track: "bg-loss/15", bar: "bg-loss" },
};

export interface KpiCardProps {
  label: string;
  value: string;
  tone?: KpiTone;
  /** A soft pill beside the value — the mock-up's « +12.5% ». */
  badge?: ReactNode;
  /** One line under the value: its unit, source, or what it is a share of. */
  detail?: string;
  /** 0..100, drawn as the mock-up's thin « Target Progress » bar. */
  progress?: number;
  progressTone?: KpiTone;
  icon?: LucideIcon;
  untrusted?: boolean;
  className?: string;
}

/**
 * A KPI tile after the reference mock-up's « Total Trading Capital »: a small
 * grey label, one large light number, an optional pill and thin bar, one line
 * of context. The number is the point; everything else stays quiet.
 */
export function KpiCard({
  label,
  value,
  tone = "default",
  badge,
  detail,
  progress,
  progressTone,
  icon: Icon,
  untrusted = false,
  className,
}: KpiCardProps) {
  const bar = BAR_TONE[progressTone ?? tone];
  return (
    <Card
      className={cn(
        "surface-card gap-0 rounded-2xl px-5 py-5 shadow-none transition-opacity",
        untrusted && "opacity-60",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] text-muted-foreground">{label}</p>
        {Icon && (
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground ring-1 ring-border">
            <Icon className="size-4" strokeWidth={1.75} />
          </span>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className={cn("tnum text-3xl font-light tracking-tight", VALUE_TONE[tone])}>{value}</p>
        {badge}
      </div>
      {progress !== undefined && (
        <Progress
          value={Math.max(0, Math.min(100, progress))}
          className={cn("mt-4 h-1.5", bar.track)}
          indicatorClassName={bar.bar}
        />
      )}
      {detail && <p className="mt-3 text-xs text-muted-foreground">{detail}</p>}
    </Card>
  );
}
