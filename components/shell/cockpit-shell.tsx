"use client";

import type { ReactNode } from "react";
import { LockoutAckBanner } from "./lockout-ack-banner";
import { LockoutViolationBanner } from "./lockout-violation-banner";
import { SidebarNav } from "./sidebar-nav";
import { SiteHeader } from "./site-header";

/**
 * The cockpit frame (ADR 0017, ExponentValue): a fixed 16 rem sidebar from
 * `lg`, a sticky top bar, the lockout banners — which stay full width and
 * above everything, they are safety — then the screen in a centred
 * `max-w-6xl` container shared by the bar, the page and the footer so their
 * left edges line up.
 */
export function CockpitShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh">
      <aside className="sticky top-0 hidden h-svh w-64 shrink-0 border-r border-sidebar-border bg-sidebar lg:block">
        <SidebarNav />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <SiteHeader />
        <LockoutAckBanner />
        <LockoutViolationBanner />

        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>

        <footer className="border-t px-4 sm:px-6 lg:px-10">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-1 py-5 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <p>Trading OS — poste de travail personnel pour trader intraday</p>
            <p>Le process est le produit, pas le signal.</p>
          </div>
        </footer>
      </div>
    </div>
  );
}
