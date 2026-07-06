interface EmptyStateProps {
  title: string;
  description: string;
  hint?: string;
}

export function EmptyState({ title, description, hint }: EmptyStateProps) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface p-8 text-center">
      <h2 className="text-sm font-medium text-foreground">{title}</h2>
      <p className="max-w-md text-sm text-muted">{description}</p>
      {hint && (
        <p className="mt-2 rounded border border-border bg-surface-elevated px-2 py-1 text-xs text-muted">
          {hint}
        </p>
      )}
    </div>
  );
}
