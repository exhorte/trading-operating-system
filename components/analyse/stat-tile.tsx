import { cn } from "cn";

interface StatTileProps {
  label: string;
  value: string;
  /** What the number is, in one line — the ⓘ made permanent. */
  detail: string;
  tone?: "profit" | "loss" | "default";
}

const TONE_CLASSES: Record<NonNullable<StatTileProps["tone"]>, string> = {
  profit: "text-success",
  loss: "text-destructive",
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
    <div className="rounded-lg border bg-muted/40 px-3.5 py-3">
      <p className="text-[0.8125rem] text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-lg font-semibold tracking-tight tabular-nums", TONE_CLASSES[tone])}>{value}</p>
      <p className="mt-0.5 text-xs leading-snug text-muted-foreground">{detail}</p>
    </div>
  );
}
