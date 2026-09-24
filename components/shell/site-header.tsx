"use client";

import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { AccountMenu } from "./account-menu";
import { navEntryFor, SECTION_LABELS } from "./nav";

/**
 * The top bar, reduced to what the reference mock-up keeps: the page title
 * with its breadcrumb on the left, the account on the right. Everything that
 * used to crowd it moved to where it is read (2026-09-24 redesign):
 *
 *   compliance rate  -> first card of the Command Center (T07)
 *   news / blackout  -> bottom of the sidebar, on every screen (T03)
 *   emergency stop   -> bottom of the sidebar, on every screen (T02a)
 *   link, persistence, environment -> the account menu and its status dot
 */
export function SiteHeader() {
  const pathname = usePathname();
  const entry = navEntryFor(pathname);
  const title = entry?.label ?? "Trading OS";

  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/70 md:px-6">
      <SidebarTrigger className="-ml-1 md:hidden" />
      <div className="min-w-0">
        <h1 className="truncate text-base font-semibold tracking-tight text-foreground">{title}</h1>
        {entry && (
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            <span>{SECTION_LABELS[entry.section]}</span>
            <ChevronRight className="size-3" strokeWidth={2} />
            <span className="truncate text-foreground/70">{title}</span>
          </p>
        )}
      </div>
      <div className="ml-auto">
        <AccountMenu />
      </div>
    </header>
  );
}
