import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "cn";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "./card";

interface PanelProps {
  title?: ReactNode;
  description?: ReactNode;
  /** A line icon in a bordered square beside the title. */
  icon?: LucideIcon;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  /** Dim the panel when realtime data can no longer be trusted. */
  untrusted?: boolean;
}

/**
 * The cockpit's card: a `Card` with the app's conventions — a title row with
 * optional icon, description and actions, `p-5` padding, a hairline border.
 * Every screen builds on this, so the look changes here, once. The key
 * figures of a screen do NOT go in a Panel: they go in the dark
 * `MetricPanel` (components/ui/metric-panel.tsx).
 */
export function Panel({
  title,
  description,
  icon: Icon,
  actions,
  children,
  className,
  contentClassName,
  untrusted = false,
}: PanelProps) {
  const hasHeader = Boolean(title || description || actions || Icon);
  return (
    <Card className={cn("gap-4 py-5 transition-opacity", untrusted && "opacity-60", className)}>
      {hasHeader && (
        <CardHeader className="gap-1 px-5">
          <div className="flex min-w-0 items-start gap-3">
            {Icon && (
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background shadow-xs">
                <Icon className="size-4" aria-hidden="true" />
              </span>
            )}
            <div className="min-w-0 self-center">
              {title && <CardTitle className="text-sm leading-snug font-semibold [overflow-wrap:anywhere]">{title}</CardTitle>}
              {description && (
                <CardDescription className="mt-0.5 text-sm leading-snug">{description}</CardDescription>
              )}
            </div>
          </div>
          {actions && <CardAction className="self-center">{actions}</CardAction>}
        </CardHeader>
      )}
      <CardContent className={cn("px-5", contentClassName)}>{children}</CardContent>
    </Card>
  );
}
