import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "cn";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "./card";

interface PanelProps {
  title?: ReactNode;
  description?: ReactNode;
  /** A line icon in a soft square beside the title, as on the mock-up. */
  icon?: LucideIcon;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  /** Dim the panel when realtime data can no longer be trusted. */
  untrusted?: boolean;
  /**
   * The one panel per screen that answers the screen's question gets the
   * glow — mint when the answer is good, coral when it is not. More than one
   * per screen and it stops meaning anything.
   */
  highlight?: "primary" | "loss";
}

/**
 * The cockpit's card: a shadcn `Card` with the app's conventions — a title
 * row with optional icon, description and actions, generous padding, and
 * the reference mock-up's surface (one step above the page, lit from the
 * top). Every screen builds on this, so the look changes here, once.
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
  highlight,
}: PanelProps) {
  const hasHeader = Boolean(title || description || actions || Icon);
  return (
    <Card
      className={cn(
        "surface-card gap-4 rounded-2xl py-5 shadow-none transition-opacity",
        highlight === "primary" && "surface-glow",
        highlight === "loss" && "surface-glow-loss",
        untrusted && "opacity-60",
        className,
      )}
    >
      {hasHeader && (
        <CardHeader className="gap-1 px-5">
          <div className="flex min-w-0 items-center gap-3">
            {Icon && (
              <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-muted text-primary ring-1 ring-border">
                <Icon className="size-[18px]" strokeWidth={1.75} />
              </span>
            )}
            <div className="min-w-0">
              {title && <CardTitle className="truncate text-sm font-medium text-foreground">{title}</CardTitle>}
              {description && (
                <CardDescription className="mt-1 text-xs leading-snug">{description}</CardDescription>
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
