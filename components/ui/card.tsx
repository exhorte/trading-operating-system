import type { ReactNode } from "react";

interface CardProps {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Dim the card when realtime data can no longer be trusted. */
  untrusted?: boolean;
}

export function Card({ title, actions, children, className = "", untrusted = false }: CardProps) {
  return (
    <section
      className={`rounded-lg border border-border bg-surface ${
        untrusted ? "opacity-60" : ""
      } ${className}`}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          {title && (
            <h2 className="text-xs font-medium uppercase tracking-wider text-muted">{title}</h2>
          )}
          {actions}
        </header>
      )}
      <div className="p-3">{children}</div>
    </section>
  );
}
