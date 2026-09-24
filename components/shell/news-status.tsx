"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CalendarClock } from "lucide-react";
import { cn } from "cn";
import { useCockpit } from "@/lib/realtime/provider";
import { defaultRiskPolicy, isNewsBlackout, nextRelease } from "@/lib/risk";
import { SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";

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
 * every screen (the fiche's own requirement). Lived in the top bar until the
 * 2026-09-24 redesign; now pinned at the bottom of the sidebar, where it
 * stays on every page. Reads `upcomingReleases` directly so it works before
 * an account is connected (the calendar is global). Absent data is shown as
 * the news gate treats it: closed, never as a reassuring blank.
 */
export function NewsStatus() {
  const { upcomingReleases, account } = useCockpit();
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const interval = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(interval);
  }, []);

  let line: NewsLine;
  let blackout = false;
  if (upcomingReleases === null) {
    line = { title: "Calendrier indisponible", detail: "gate publications fermée", tone: "loss" };
  } else {
    const policy = defaultRiskPolicy(account?.accountId ?? "unknown");
    const nowIso = new Date(nowMs).toISOString();
    const upcoming = nextRelease(nowIso, upcomingReleases);
    if (!upcoming) {
      line = { title: "Aucune publication", detail: "rien de prévu au calendrier", tone: "muted" };
    } else {
      blackout = isNewsBlackout(nowIso, upcomingReleases, policy.newsBlackoutMinutes);
      line = {
        title: `${upcoming.label} dans ${formatCountdown(upcoming.scheduledAt, nowMs)}`,
        detail: blackout
          ? `blackout en cours (±${policy.newsBlackoutMinutes} min)`
          : `blackout à ${formatClock(upcoming.scheduledAt)}`,
        tone: blackout ? "warning" : "muted",
      };
    }
  }

  const toneText = line.tone === "loss" ? "text-loss" : line.tone === "warning" ? "text-warning" : "text-sidebar-foreground";

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        size="lg"
        tooltip={`${line.title} — ${line.detail}`}
        // The lg size drops its padding in the icon rail; put it back so the
        // icon sits centred like every other item.
        className="gap-3 group-data-[collapsible=icon]:p-2.5!"
      >
        <Link href="/market-context">
          <span className="relative flex shrink-0">
            <CalendarClock className={cn("size-5", toneText)} strokeWidth={1.75} />
            {line.tone !== "muted" && (
              <span
                className={cn(
                  "absolute -top-0.5 -right-0.5 size-2 rounded-full",
                  line.tone === "loss" ? "bg-loss" : "bg-warning",
                  blackout && "animate-pulse",
                )}
                aria-hidden
              />
            )}
          </span>
          <span className="flex min-w-0 flex-col leading-tight group-data-[collapsible=icon]:hidden">
            <span className={cn("truncate text-[13px] font-medium", toneText)}>{line.title}</span>
            <span className="truncate text-[11px] text-muted-foreground">{line.detail}</span>
          </span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
