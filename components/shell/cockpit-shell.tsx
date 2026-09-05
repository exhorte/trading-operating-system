"use client";

import { useState, type ReactNode } from "react";
import { IconRail, Sidebar } from "./sidebar";
import { TopCommandBar } from "./top-command-bar";
import { KillSwitchBanner } from "./kill-switch-banner";
import { SizingPanel } from "@/components/cockpit/sizing-panel";
import { TicketPanel } from "@/components/cockpit/ticket-panel";
import { TradeDraftProvider } from "@/components/cockpit/trade-draft-context";

export function CockpitShell({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex h-dvh overflow-hidden">
      <IconRail />
      <Sidebar open={sidebarOpen} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopCommandBar onToggleSidebar={() => setSidebarOpen((open) => !open)} />
        <KillSwitchBanner />
        <main className="min-h-0 flex-1 overflow-y-auto p-3">{children}</main>
      </div>
      {/* T01 + T04: permanent, visible on every route without navigation. */}
      <aside className="hidden w-72 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border bg-surface p-3 xl:flex">
        <TradeDraftProvider>
          <SizingPanel />
          <TicketPanel />
        </TradeDraftProvider>
      </aside>
    </div>
  );
}
