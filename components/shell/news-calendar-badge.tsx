"use client";

import { useEffect, useState } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { defaultRiskPolicy, isNewsBlackout, nextRelease } from "@/lib/risk";
import { StatusPill } from "@/components/ui/status-pill";

function formatCountdown(untilIso: string, nowMs: number): string {
  const remainingMs = Math.max(0, Date.parse(untilIso) - nowMs);
  const totalMinutes = Math.floor(remainingMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h${minutes.toString().padStart(2, "0")}` : `${minutes}min`;
}

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/**
 * T03 — permanent, always visible (not tucked in a tab), per the card's
 * acceptance criterion. Reads store.upcomingReleases directly rather than
 * `risk.gates`' news entry so this keeps working even before an account is
 * connected (the calendar is global, not account-scoped).
 */
export function NewsCalendarBadge() {
  const { upcomingReleases, account } = useCockpit();
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const interval = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(interval);
  }, []);

  // T03-gate-news.md: absent data fails the RISK gate closed; this badge
  // mirrors that honestly rather than showing a reassuring blank space.
  if (upcomingReleases === null) {
    return (
      <span title="FRED calendar cache not loaded yet — the news gate is failing closed">
        <StatusPill tone="loss">News: no data</StatusPill>
      </span>
    );
  }

  const policy = defaultRiskPolicy(account?.accountId ?? "unknown");
  const nowIso = new Date(nowMs).toISOString();
  const upcoming = nextRelease(nowIso, upcomingReleases);

  if (!upcoming) {
    return <StatusPill tone="muted">News: nothing scheduled</StatusPill>;
  }

  const blackout = isNewsBlackout(nowIso, upcomingReleases, policy.newsBlackoutMinutes);
  return (
    <span title={`±${policy.newsBlackoutMinutes}min blackout around whitelisted FRED releases`}>
      <StatusPill tone={blackout ? "warning" : "muted"} pulse={blackout}>
        {upcoming.label} in {formatCountdown(upcoming.scheduledAt, nowMs)} — blackout at {formatClock(upcoming.scheduledAt)}
      </StatusPill>
    </span>
  );
}
