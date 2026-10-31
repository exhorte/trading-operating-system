"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";
import { KillSwitchButton } from "./kill-switch-button";
import { Logo } from "./logo";
import { NewsStatus } from "./news-status";
import { isNavItemActive, NAV_ITEMS, SECTION_LABELS, SETTINGS_ITEM, type NavItem } from "./nav";

/** Class of a navigation item — exported so the news status can sit in the same list. */
export const navItemClass = (active: boolean) =>
  cn(
    "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors outline-none",
    "focus-visible:ring-[3px] focus-visible:ring-ring/40 [&_svg]:size-4 [&_svg]:shrink-0",
    active
      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground shadow-xs ring-1 ring-sidebar-border"
      : "text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
  );

function NavLink({ item, pathname, onNavigate }: { item: NavItem; pathname: string; onNavigate?: () => void }) {
  const Icon = item.icon;
  const active = isNavItemActive(pathname, item);
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={navItemClass(active)}
    >
      <Icon aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
    </Link>
  );
}

const SECTIONS: NavItem["section"][] = ["operate", "analyze", "system"];

/**
 * The sidebar's content, shared by the fixed column (desktop) and the mobile
 * drawer. Logo row (h-16, aligned with the top bar), the screens grouped by
 * what one does with them, and — pinned at the bottom, reachable from every
 * screen, drawer included — the permanent news status (T03), the emergency
 * stop (T02a) and Settings. Safety does not follow the aesthetics (ADR 0012).
 */
export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 shrink-0 items-center border-b border-sidebar-border px-5">
        <Link
          href="/"
          onClick={onNavigate}
          aria-label="Trading OS — Command Center"
          className="rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40"
        >
          <Logo />
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-6" aria-label="Navigation principale">
        {SECTIONS.map((section, index) => (
          <div key={section} className={cn(index > 0 && "mt-8")}>
            <p className="px-3 text-[11px] font-medium tracking-wider text-sidebar-foreground uppercase">
              {SECTION_LABELS[section]}
            </p>
            <ul className="mt-3 flex flex-col gap-1">
              {NAV_ITEMS.filter((item) => item.section === section).map((item) => (
                <li key={item.href}>
                  <NavLink item={item} pathname={pathname} onNavigate={onNavigate} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="flex shrink-0 flex-col gap-1 border-t border-sidebar-border p-3">
        <NewsStatus onNavigate={onNavigate} />
        <KillSwitchButton />
        <NavLink item={SETTINGS_ITEM} pathname={pathname} onNavigate={onNavigate} />
      </div>
    </div>
  );
}
