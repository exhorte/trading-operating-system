"use client";

import { useEffect, useState } from "react";
import { CalendarClock } from "lucide-react";
import { useCockpit } from "@/lib/realtime/provider";
import { defaultRiskPolicy } from "@/lib/risk";
import type { UpcomingRelease } from "@/lib/risk/news-calendar";
import { SectionHeading } from "@/components/shell/page-header";
import { Callout } from "@/components/ui/callout";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
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
 * single next-release line of the sidebar.
 *
 * Reads `upcomingReleases` from the store directly (same source as the
 * sidebar's news status) — the calendar is global, not account-scoped, so
 * this renders before any account is connected. A null cache is shown as a
 * failure, not as an empty calendar: the gate fails closed, and this screen
 * must not read calmer than the gate behaves (T03-gate-news.md).
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

  const heading = (actions?: React.ReactNode) => (
    <SectionHeading
      title="Calendrier économique"
      subtitle="les publications FRED sur lesquelles la gate news tourne"
      icon={CalendarClock}
      actions={actions}
    />
  );

  if (upcomingReleases === null) {
    return (
      <section className="flex flex-col gap-4">
        {heading(<StatusPill tone="loss">cache absent</StatusPill>)}
        <Callout title="Calendrier indisponible" variant="warning">
          Le cache FRED n&apos;est pas chargé. La gate news échoue fermée — aucune séance ne sera autorisée tant que ce
          cache est vide. Vérifier <code className="text-foreground">FRED_API_KEY</code> dans{" "}
          <code className="text-foreground">04_code/.env</code>.
        </Callout>
      </section>
    );
  }

  const upcoming = upcomingReleases
    .filter((release) => Date.parse(release.scheduledAt) + blackoutMinutes * MINUTE_MS > nowMs)
    .sort((a, b) => Date.parse(a.scheduledAt) - Date.parse(b.scheduledAt));

  const inBlackout = (release: UpcomingRelease) =>
    Math.abs(Date.parse(release.scheduledAt) - nowMs) <= blackoutMinutes * MINUTE_MS;

  const StateBadge = ({ release }: { release: UpcomingRelease }) => (
    <StatusPill tone={inBlackout(release) ? "warning" : "muted"} pulse={inBlackout(release)}>
      {inBlackout(release) ? "blackout" : "à venir"}
    </StatusPill>
  );

  const columns: Column<UpcomingRelease>[] = [
    { key: "label", header: "Publication", cell: (r) => <span className="font-medium">{r.label}</span> },
    { key: "when", header: "Quand", cell: (r) => <span className="text-muted-foreground">{formatWhen(r.scheduledAt)}</span> },
    {
      key: "window",
      header: "Fenêtre de blackout",
      cell: (r) => <span className="text-muted-foreground">{formatWindow(r.scheduledAt, blackoutMinutes)}</span>,
    },
    { key: "state", header: "État", align: "right", cell: (r) => <StateBadge release={r} /> },
  ];

  return (
    <section className="flex flex-col gap-4">
      {heading(
        <span className="text-sm text-muted-foreground">
          blackout ±{blackoutMinutes} min · {upcomingReleases.length} publication(s) en cache
        </span>,
      )}
      {upcoming.length === 0 ? (
        <p className="rounded-xl border border-dashed px-6 py-8 text-center text-sm text-muted-foreground">
          Aucune publication à venir dans le cache. La gate news laisse passer.
        </p>
      ) : (
        <DataList
          rows={upcoming}
          columns={columns}
          rowKey={(r) => `${r.releaseId}-${r.scheduledAt}`}
          mobileCard={(r) => (
            <>
              <MobileCardHeader name={r.label} subtitle={formatWhen(r.scheduledAt)} badge={<StateBadge release={r} />} />
              <MobileFields fields={[{ label: "Fenêtre", value: formatWindow(r.scheduledAt, blackoutMinutes) }]} />
            </>
          )}
        />
      )}
    </section>
  );
}
