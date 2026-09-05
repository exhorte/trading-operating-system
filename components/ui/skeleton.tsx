export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded bg-surface-elevated ${className}`}
      aria-hidden
    />
  );
}
