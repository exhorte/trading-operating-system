import type { ReactNode } from "react";
import { cn } from "cn";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./table";

export type Column<T> = {
  key: string;
  header: string;
  /** Amounts and percentages align right. */
  align?: "left" | "right";
  /**
   * Classes of the column's CELLS only. The header keeps the dark-header
   * colours: a `text-muted-foreground` meant for a cell turned its header grey
   * on near-black (a 3:1 contrast) before this was kept out of it.
   */
  className?: string;
  cell: (row: T) => ReactNode;
};

/**
 * The main list of a screen: a dark-header table from `md` up, stacked cards
 * below. The table scrolls INSIDE its container when needed (cells are
 * `whitespace-nowrap`), never the page.
 */
export function DataList<T>({
  rows,
  columns,
  rowKey,
  mobileCard,
  rowClassName,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  /** Content of one mobile card (see `MobileCardHeader` and `MobileFields`). */
  mobileCard: (row: T) => ReactNode;
  rowClassName?: (row: T) => string | undefined;
}) {
  return (
    <>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((column) => (
                <TableHead key={column.key} className={cn(column.align === "right" && "text-right")}>
                  {column.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={rowKey(row)} className={rowClassName?.(row)}>
                {columns.map((column) => (
                  <TableCell
                    key={column.key}
                    className={cn(column.align === "right" && "text-right tabular-nums", column.className)}
                  >
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="flex flex-col gap-3 md:hidden">
        {rows.map((row) => (
          <li key={rowKey(row)} className="rounded-xl border bg-card p-4 shadow-xs">
            {mobileCard(row)}
          </li>
        ))}
      </ul>
    </>
  );
}

/** Round monogram heading a row (the « token » of the mock-ups). */
export function Monogram({ name, className }: { name: string; className?: string }) {
  const initials =
    name
      .replace(/[^A-Za-z0-9]+/g, " ")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]!.toUpperCase())
      .join("") || "?";
  return (
    <span
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-[0.6875rem] font-semibold ring-1 ring-border",
        className,
      )}
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}

/**
 * First line of a mobile card: monogram, title, subtitle and a status badge.
 * It wraps: a long badge (« precondition_session_window ») drops to its own
 * row rather than squeezing the title — the symbol is what identifies the card.
 */
export function MobileCardHeader({
  name,
  subtitle,
  badge,
}: {
  name: string;
  subtitle?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <Monogram name={name} />
      {/* `flex-[1_1_7rem]`, not `flex-1 basis-28`: in Tailwind 4 `flex-1` (basis 0%) wins over `basis-*`,
          and with a zero basis the badge never wraps — it just squeezes the name. */}
      <div className="min-w-0 flex-[1_1_7rem]">
        <p className="font-medium [overflow-wrap:anywhere]">{name}</p>
        {subtitle && <p className="truncate text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      {badge && <div className="max-w-full shrink-0">{badge}</div>}
    </div>
  );
}

/**
 * Label (grey) / value (bold) grid of a mobile card, three per row. A value
 * wraps instead of being cut: a lockout reason or a date is information, and
 * a code without spaces (« consecutive_losses_pause ») may break anywhere.
 */
export function MobileFields({ fields }: { fields: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="mt-4 grid grid-cols-3 gap-x-3 gap-y-3 text-sm">
      {fields.map((field) => (
        <div key={field.label} className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-xs text-muted-foreground">{field.label}</dt>
          <dd className="font-medium tabular-nums [overflow-wrap:anywhere]">{field.value}</dd>
        </div>
      ))}
    </dl>
  );
}
