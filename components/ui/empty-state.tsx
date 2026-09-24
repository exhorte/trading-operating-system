import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  title: string;
  description: string;
  hint?: string;
  icon?: LucideIcon;
}

export function EmptyState({ title, description, hint, icon: Icon = Inbox }: EmptyStateProps) {
  return (
    <div className="surface-card flex min-h-[40vh] flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border bg-card p-10 text-center">
      <span className="flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground ring-1 ring-border">
        <Icon className="size-6" strokeWidth={1.5} />
      </span>
      <h2 className="text-base font-medium text-foreground">{title}</h2>
      <p className="max-w-md text-sm leading-relaxed text-muted-foreground">{description}</p>
      {hint && (
        <p className="mt-1 rounded-lg bg-muted px-3 py-1.5 text-xs text-muted-foreground ring-1 ring-border">
          {hint}
        </p>
      )}
    </div>
  );
}
