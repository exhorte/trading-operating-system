import { cn } from "cn";

/** The product mark: a thin ring, a solid disc and the monogram. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8 shrink-0", className)} aria-hidden="true" focusable="false">
      <circle cx="16" cy="16" r="15.25" className="fill-background stroke-border" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="12.5" className="fill-primary" />
      <text
        x="16"
        y="16"
        textAnchor="middle"
        dominantBaseline="central"
        className="fill-primary-foreground"
        fontSize="10"
        fontWeight="700"
        letterSpacing="-0.3"
      >
        TO
      </text>
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="flex flex-col leading-none">
        <span className="text-sm font-semibold tracking-tight text-foreground">Trading OS</span>
        <span className="mt-1 text-[11px] font-medium text-muted-foreground">Poste de travail intraday</span>
      </span>
    </span>
  );
}
