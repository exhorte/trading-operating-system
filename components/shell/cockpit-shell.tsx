"use client";

import type { ReactNode } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "./app-sidebar";
import { LockoutAckBanner } from "./lockout-ack-banner";
import { LockoutViolationBanner } from "./lockout-violation-banner";
import { SiteHeader } from "./site-header";

/**
 * The cockpit frame (2026-09-24 redesign on shadcn/ui, after the reference
 * mock-up in 05_screenchot/dashboar.jpg): a collapsible sidebar, a quiet
 * header, the lockout banners — which stay full width and above everything,
 * they are safety — then the screen itself, with room to breathe.
 */
export function CockpitShell({ children }: { children: ReactNode }) {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <SiteHeader />
        <LockoutAckBanner />
        <LockoutViolationBanner />
        <div className="flex-1 p-4 md:p-6">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}
