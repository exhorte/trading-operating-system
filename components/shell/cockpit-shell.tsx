"use client";

import { useState, type ReactNode } from "react";
import { IconRail, Sidebar } from "./sidebar";
import { TopCommandBar } from "./top-command-bar";
import { SizingPanel } from "@/components/cockpit/sizing-panel";

export function CockpitShell({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex h-dvh overflow-hidden">
      <IconRail />
      <Sidebar open={sidebarOpen} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopCommandBar onToggleSidebar={() => setSidebarOpen((open) => !open)} />
        <main className="min-h-0 flex-1 overflow-y-auto p-3">{children}</main>
      </div>
      {/* T01: permanent, visible on every route without navigation. */}
      <aside className="hidden w-72 shrink-0 flex-col overflow-y-auto border-l border-border bg-surface p-3 xl:flex">
        <SizingPanel />
      </aside>
    </div>
  );
}
