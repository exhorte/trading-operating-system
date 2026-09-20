interface StatTileProps {
  label: string;
  value: string;
  /** What the number is, in one line — the ⓘ made permanent. */
  detail: string;
  tone?: "profit" | "loss" | "default";
}

const TONE_CLASSES: Record<NonNullable<StatTileProps["tone"]>, string> = {
  profit: "text-profit",
  loss: "text-loss",
  default: "text-foreground",
};

/**
 * One statistic with its definition attached.
 *
 * FTMO's MetriX puts an ⓘ on each of its eleven tiles; the definition is one
 * hover away and therefore, in practice, unread. Same cost in vertical space
 * to just print it.
 */
export function StatTile({ label, value, detail, tone = "default" }: StatTileProps) {
  return (
    <div className="rounded border border-border bg-surface-elevated px-2.5 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className={`tnum mt-0.5 text-base font-semibold ${TONE_CLASSES[tone]}`}>{value}</p>
      <p className="mt-0.5 text-[10px] leading-tight text-muted">{detail}</p>
    </div>
  );
}
