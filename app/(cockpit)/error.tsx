"use client";

export default function CockpitError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 rounded-lg border border-loss/40 bg-surface p-8 text-center">
      <h2 className="text-sm font-semibold text-loss">Cockpit panel failed</h2>
      <p className="max-w-md text-sm text-muted">
        {error.message || "An unexpected error occurred while rendering this screen."}
      </p>
      <button
        type="button"
        onClick={reset}
        className="rounded border border-border bg-surface-elevated px-3 py-1.5 text-xs hover:text-foreground"
      >
        Try again
      </button>
    </div>
  );
}
