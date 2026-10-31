"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CalendarClock } from "lucide-react";
import { cn } from "cn";
import { useCockpit } from "@/lib/realtime/provider";
import { inBlackout, nextRelease } from "@/lib/cockpit/calendar";

function formatCountdown(untilIso: string, nowMs: number): string {
  const remainingMs = Math.max(0, Date.parse(untilIso) - nowMs);
  const totalMinutes = Math.floor(remainingMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h${minutes.toString().padStart(2, "0")}` : `${minutes} min`;
}

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

interface NewsLine {
  title: string;
  detail: string;
  tone: "loss" | "warning" | "muted";
}

/**
 * T03 — the next FRED release and its blackout, permanent and visible from
 * every screen (the fiche's own requirement): pinned at the bottom of the
 * sidebar. Reads `upcomingReleases` directly so it works before an account
 * is connected (the calendar is global). Absent data is shown as the news
 * gate treats it: closed, never as a reassuring blank. Whether an entry is
 * allowed is the core's gate; the blackout window shown here is the active
 * account's own rule, and none is claimed before there is an account.
 */
export function NewsStatus({ onNavigate }: { onNavigate?: () => void }) {
  const { upcomingReleases, registered } = useCockpit();
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const interval = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(interval);
  }, []);

  const blackoutMinutes = registered?.riskProfile.news.blackoutMinutes ?? null;

  let line: NewsLine;
  let blackout = false;
  if (upcomingReleases === null) {
    line = { title: "Calendrier indisponible", detail: "gate publications fermée", tone: "loss" };
  } else {
    const upcoming = nextRelease(nowMs, upcomingReleases);
    if (!upcoming) {
      line = { title: "Aucune publication", detail: "rien de prévu au calendrier", tone: "muted" };
    } else {
      blackout = blackoutMinutes !== null && inBlackout(nowMs, upcoming, blackoutMinutes);
      line = {
        title: `${upcoming.label} dans ${formatCountdown(upcoming.scheduledAt, nowMs)}`,
        detail: blackout
          ? `blackout en cours (±${blackoutMinutes} min)`
          : blackoutMinutes === null
            ? `publication à ${formatClock(upcoming.scheduledAt)}`
            : `blackout à ${formatClock(upcoming.scheduledAt)}`,
        tone: blackout ? "warning" : "muted",
      };
    }
  }

  const toneText = line.tone === "loss" ? "text-destructive" : line.tone === "warning" ? "text-warning" : "text-foreground";

  return (
    <Link
      href="/market-context"
      onClick={onNavigate}
      title={`${line.title} — ${line.detail}`}
      className={cn(
        "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors outline-none",
        "text-sidebar-foreground hover:bg-sidebar-accent/70 focus-visible:ring-[3px] focus-visible:ring-ring/40",
      )}
    >
      <span className="relative flex shrink-0">
        <CalendarClock className="size-4" aria-hidden="true" />
        {line.tone !== "muted" && (
          <span
            className={cn(
              "absolute -top-1 -right-1 size-2 rounded-full",
              line.tone === "loss" ? "bg-destructive" : "bg-warning",
              blackout && "animate-pulse",
            )}
            aria-hidden="true"
          />
        )}
      </span>
      <span className="flex min-w-0 flex-col leading-tight">
        <span className={cn("truncate text-[13px] font-medium", toneText)}>{line.title}</span>
        <span className="truncate text-[11px] text-sidebar-foreground">{line.detail}</span>
      </span>
    </Link>
  );
}
