"use client";

import { useComplianceRate } from "@/lib/compliance/use-compliance-rate";
import { VIOLATION_LABELS } from "@/lib/compliance/labels";
import type { ViolationType } from "@/lib/compliance/violations";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";

/** Same thresholds as the top-bar badge — one rule, read twice. */
function band(rate: number): { label: string; color: string; tone: string } {
  if (rate >= 0.9) {
    return { label: "Conforme", color: "var(--profit)", tone: "text-profit" };
  }
  if (rate >= 0.7) {
    return { label: "À surveiller", color: "var(--warning)", tone: "text-warning" };
  }
  return { label: "Hors cadre", color: "var(--loss)", tone: "text-loss" };
}

const RADIUS = 58;
const CENTER_X = 70;
const CENTER_Y = 66;
const STROKE = 10;
const ARC_LENGTH = Math.PI * RADIUS;
const ARC_PATH = `M ${CENTER_X - RADIUS} ${CENTER_Y} A ${RADIUS} ${RADIUS} 0 0 1 ${CENTER_X + RADIUS} ${CENTER_Y}`;

/**
 * The discipline score, borrowed in form from FTMO's MetriX gauge and
 * re-pointed at what this product actually measures.
 *
 * FTMO puts a discipline score *beside* the P&L; here the process is the
 * product (ADR 0001), so this is the screen's headline and there is no P&L on
 * it at all. The number is T07's weekly compliance rate — the same value the
 * top bar shows, from the same hook.
 *
 * The breakdown below the gauge is the attribution rail from the trade-journal
 * reference, counted in occurrences per violation type rather than in dollars:
 * a violation has a gate and a count, not a price
 * (context/frontend/visual_reference_ftmo_journal.md).
 */
export function DisciplineGauge() {
  const { rate, tradeCount, breachedCount, byType, lookbackDays, failed } = useComplianceRate();

  if (rate === null) {
    // "Could not read" and "still reading" must not look alike: an endless
    // skeleton reads as patience when the backend is actually down.
    return (
      <Panel title="Score de discipline">
        {failed ? (
          <p className="rounded-xl border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
            Trades clôturés illisibles — le backend répond-il ?
          </p>
        ) : (
          <Skeleton className="h-52 rounded-xl" />
        )}
      </Panel>
    );
  }

  const { label, color, tone } = band(rate);
  const percent = Math.round(rate * 100);
  const entries = (Object.keys(byType) as ViolationType[])
    .map((type) => ({ type, count: byType[type] }))
    .sort((a, b) => b.count - a.count);
  const maxCount = Math.max(1, ...entries.map((e) => e.count));

  return (
    <Panel
      title="Score de discipline"
      actions={<span className="text-xs text-muted-foreground">{lookbackDays} derniers jours</span>}
    >
      <div className="flex flex-col items-center">
        <svg viewBox="0 0 140 78" className="w-full max-w-[220px]" role="img"
          aria-label={`Score de discipline ${percent} %, ${label}`}>
          <path
            d={ARC_PATH}
            fill="none"
            stroke="var(--muted)"
            strokeWidth={STROKE}
            strokeLinecap="round"
          />
          <path
            d={ARC_PATH}
            fill="none"
            stroke={color}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={`${rate * ARC_LENGTH} ${ARC_LENGTH}`}
          />
          <text
            x={CENTER_X}
            y={CENTER_Y - 12}
            textAnchor="middle"
            className="tnum"
            fill={color}
            fontSize="24"
            fontWeight="600"
          >
            {percent}%
          </text>
          <text
            x={CENTER_X}
            y={CENTER_Y + 4}
            textAnchor="middle"
            fill="var(--muted-foreground)"
            fontSize="10"
          >
            {label}
          </text>
        </svg>

        <p className="mt-1 text-xs text-muted-foreground">
          <span className={`tnum font-medium ${tone}`}>{breachedCount}</span> trade(s) non
          conforme(s) sur <span className="tnum text-foreground">{tradeCount}</span>
        </p>
      </div>

      <div className="mt-3 border-t border-border pt-3">
        <p className="mb-2 text-xs text-muted-foreground">
          Par type de manquement
        </p>
        {tradeCount === 0 ? (
          <p className="text-xs text-muted-foreground">
            Aucun trade clôturé sur la période — le score vaut 100 % par défaut, il ne dit
            rien.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {entries.map(({ type, count }) => (
              <li key={type}>
                <div className="flex items-baseline justify-between gap-2 text-xs">
                  <span className={count > 0 ? "text-foreground" : "text-muted-foreground"}>
                    {VIOLATION_LABELS[type]}
                  </span>
                  <span className="tnum text-muted-foreground">{count}</span>
                </div>
                <Progress
                  value={(count / maxCount) * 100}
                  className="mt-1.5 h-1 bg-muted"
                  indicatorClassName={count > 0 ? "bg-loss" : "bg-transparent"}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
