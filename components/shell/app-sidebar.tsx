"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, PanelLeft } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarSeparator,
  useSidebar,
} from "@/components/ui/sidebar";
import { KillSwitchButton } from "./kill-switch-button";
import { NewsStatus } from "./news-status";
import { isNavItemActive, NAV_ITEMS, SECTION_LABELS, SETTINGS_ITEM, type NavItem } from "./nav";

/** Active item: a soft pill with the icon in mint — the mock-up's « Overview ». */
const ACTIVE_ITEM =
  "gap-3 text-sidebar-foreground data-[active=true]:ring-1 data-[active=true]:ring-sidebar-border data-[active=true]:[&>svg]:text-primary";

function NavLink({ item, pathname }: { item: NavItem; pathname: string }) {
  const Icon = item.icon;
  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild isActive={isNavItemActive(pathname, item)} tooltip={item.label} className={ACTIVE_ITEM}>
        <Link href={item.href}>
          <Icon strokeWidth={1.75} />
          <span>{item.label}</span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

function Brand() {
  const { toggleSidebar } = useSidebar();
  return (
    <div className="flex items-center gap-3 px-1 py-1 group-data-[collapsible=icon]:flex-col group-data-[collapsible=icon]:px-0">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/20">
        <Activity className="size-5" strokeWidth={2} />
      </span>
      <div className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
        <p className="truncate text-sm font-semibold tracking-tight text-foreground">Trading OS</p>
        <p className="truncate text-[11px] text-muted-foreground">Poste de travail intraday</p>
      </div>
      <button
        type="button"
        onClick={toggleSidebar}
        className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
        aria-label="Replier ou déplier la navigation"
        title="Replier / déplier (Ctrl+B)"
      >
        <PanelLeft className="size-[18px]" strokeWidth={1.75} />
      </button>
    </div>
  );
}

/**
 * Navigation, in the reference mock-up's layout: brand and collapse control
 * at the top, the screens grouped by what one does with them, and — pinned
 * at the bottom, reachable from every screen — the permanent news status
 * (T03), the emergency stop (T02a) and Settings. Collapses to an icon rail
 * (Ctrl+B), tooltips naming each icon.
 */
export function AppSidebar() {
  const pathname = usePathname();
  const sections: NavItem["section"][] = ["operate", "analyze", "system"];

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="p-3">
        <Brand />
      </SidebarHeader>

      <SidebarContent className="px-1">
        {sections.map((section) => (
          <SidebarGroup key={section}>
            <SidebarGroupLabel className="text-[11px] tracking-wide text-muted-foreground/80 uppercase">
              {SECTION_LABELS[section]}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV_ITEMS.filter((item) => item.section === section).map((item) => (
                  <NavLink key={item.href} item={item} pathname={pathname} />
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarSeparator />
      <SidebarFooter className="gap-1 p-3">
        <SidebarMenu>
          <NewsStatus />
          <KillSwitchButton />
          <NavLink item={SETTINGS_ITEM} pathname={pathname} />
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
