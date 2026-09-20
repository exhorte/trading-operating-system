"use client";

import { useEffect, useState } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { defaultRiskPolicy } from "@/lib/risk";
import { Card } from "@/components/ui/card";
import { StatusPill } from "@/components/ui/status-pill";

const MINUTE_MS = 60_000;

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatWindow(iso: string, blackoutMinutes: number): string {
  const at = Date.parse(iso);
  const opts = { hour: "2-digit", minute: "2-digit" } as const;
  const from = new Date(at - blackoutMinutes * MINUTE_MS).toLocaleTimeString(undefined, opts);
  const to = new Date(at + blackoutMinutes * MINUTE_MS).toLocaleTimeString(undefined, opts);
  return `${from} → ${to}`;
}

/**
 * The FRED calendar the T03 gate actually runs on, as a list rather than the
 * single next-release chip in the top bar.
 *
 * Reads `upcomingReleases` from the store directly (same source as
 * NewsCalendarBadge) — the calendar is global, not account-scoped, so this
 * renders before any account is connected. A null cache is shown as a failure,
 * not as an empty calendar: the gate fails closed, and this screen must not
 * read calmer than the gate behaves (T03-gate-news.md).
 */
export function EconomicCalendar() {
  const { upcomingReleases, account } = useCockpit();
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const interval = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(interval);
  }, []);

  const policy = defaultRiskPolicy(account?.accountId ?? "unknown");
  const blackoutMinutes = policy.newsBlackoutMinutes;

  if (upcomingReleases === null) {
    return (
      <Card
        title="Calendrier économique"
        actions={<StatusPill tone="loss">cache absent</StatusPill>}
      >
        <p className="text-xs text-muted">
          Le cache FRED n&apos;est pas chargé. La gate news échoue fermée — aucune
          séance ne sera autorisée tant que ce cache est vide. Vérifier{" "}
          <code className="text-foreground">FRED_API_KEY</code> dans{" "}
          <code className="text-foreground">04_code/.env</code>.
        </p>
      </Card>
    );
  }

  const upcoming = upcomingReleases
    .filter((release) => Date.parse(release.scheduledAt) + blackoutMinutes * MINUTE_MS > nowMs)
    .sort((a, b) => Date.parse(a.scheduledAt) - Date.parse(b.scheduledAt));

  return (
    <Card
      title="Calendrier économique"
      actions={
        <span className="text-[11px] text-muted">
          blackout ±{blackoutMinutes} min · {upcomingReleases.length} publication(s) en cache
        </span>
      }
    >
      {upcoming.length === 0 ? (
        <p className="text-xs text-muted">
          Aucune publication à venir dans le cache. La gate news laisse passer.
        </p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider text-muted">
              <th className="pb-1 font-medium">Publication</th>
              <th className="pb-1 font-medium">Quand</th>
              <th className="pb-1 font-medium">Fenêtre de blackout</th>
              <th className="pb-1 text-right font-medium">État</th>
            </tr>
          </thead>
          <tbody>
            {upcoming.map((release) => {
              const at = Date.parse(release.scheduledAt);
              const inBlackout = Math.abs(at - nowMs) <= blackoutMinutes * MINUTE_MS;
              return (
                <tr key={`${release.releaseId}-${release.scheduledAt}`} className="border-t border-border">
                  <td className="py-1.5 text-foreground">{release.label}</td>
                  <td className="tnum py-1.5 text-muted">{formatWhen(release.scheduledAt)}</td>
                  <td className="tnum py-1.5 text-muted">
                    {formatWindow(release.scheduledAt, blackoutMinutes)}
                  </td>
                  <td className="py-1.5 text-right">
                    <StatusPill tone={inBlackout ? "warning" : "muted"} pulse={inBlackout}>
                      {inBlackout ? "blackout" : "à venir"}
                    </StatusPill>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}
