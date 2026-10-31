import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "cn";
import type { NavItem } from "./nav";

/**
 * Big page title + a subtitle led by an icon. For a cockpit screen pass
 * `screen` (from `screenAt("/risk")`): the title is the screen's name and the
 * subtitle the one question it answers. Otherwise pass `title` / `subtitle`.
 */
export function PageHeader({
  screen,
  title,
  subtitle,
  icon,
  actions,
  className,
}: {
  screen?: NavItem;
  title?: ReactNode;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  actions?: ReactNode;
  className?: string;
}) {
  const heading = title ?? screen?.label;
  const lead = subtitle ?? screen?.question;
  const Icon = icon ?? screen?.icon;
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {typeof heading === "string" ? (
          <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">{heading}</h1>
        ) : (
          heading
        )}
        {lead && (
          <p className="mt-1.5 flex items-center gap-1.5 text-sm text-muted-foreground">
            {Icon && <Icon className="size-3.5 shrink-0" aria-hidden="true" />}
            <span className="min-w-0">{lead}</span>
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Title of a section inside a page (h2), with the same icon-led subtitle. */
export function SectionHeading({
  title,
  subtitle,
  icon: Icon,
  actions,
  className,
}: {
  title: string;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {subtitle && (
          <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
            {Icon && <Icon className="size-3.5 shrink-0" aria-hidden="true" />}
            <span className="min-w-0">{subtitle}</span>
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
