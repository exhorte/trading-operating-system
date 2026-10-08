import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import { cn } from "cn";
import { Card } from "./card";

interface EmptyStateProps {
  title: string;
  description: ReactNode;
  hint?: string;
  icon?: LucideIcon;
  /** Usually `<Button variant="outline" size="lg">…</Button>` or a link styled as one. */
  action?: ReactNode;
  className?: string;
}

/**
 * Illustrated empty state (ADR 0017): a large thin-line icon ringed by
 * four-pointed stars, a title and a sentence, an optional action. It stands in
 * for the screen's main card when there is nothing to show — never to say that
 * something FAILED: an unreachable backend is a `Callout variant="warning"`,
 * because « nothing happened » and « we could not ask » must not look alike.
 */
export function EmptyState({ title, description, hint, icon: Icon = Inbox, action, className }: EmptyStateProps) {
  return (
    <Card className={cn("items-center gap-0 px-6 py-14 text-center", className)}>
      <div className="relative flex size-28 items-center justify-center" aria-hidden="true">
        <Sparkle className="absolute top-1 left-2 size-4" />
        <Sparkle className="absolute top-0 right-3 size-3" />
        <Sparkle className="absolute right-0 bottom-5 size-3.5" />
        <Sparkle className="absolute bottom-2 left-4 size-2.5" />
        <Icon className="size-14 stroke-[1.25]" />
      </div>
      <h2 className="mt-4 text-base font-semibold tracking-tight">{title}</h2>
      <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">{description}</p>
      {action && <div className="mt-6">{action}</div>}
      {hint && <p className="mt-4 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  );
}

/** Decorative four-pointed star (inline SVG: no licence to carry). */
function Sparkle({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("fill-muted-foreground/25", className)} aria-hidden="true">
      <path d="M12 0c.6 6.4 5.6 11.4 12 12-6.4.6-11.4 5.6-12 12-.6-6.4-5.6-11.4-12-12C6.4 11.4 11.4 6.4 12 0Z" />
    </svg>
  );
}
