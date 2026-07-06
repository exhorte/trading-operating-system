"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "./icons";
import { NAV_ITEMS, SECTION_LABELS, type NavItem } from "./nav";

function isActive(pathname: string, item: NavItem): boolean {
  return item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
}

/** Narrow persistent icon rail (always visible). */
export function IconRail() {
  const pathname = usePathname();
  return (
    <nav
      className="flex w-12 shrink-0 flex-col items-center gap-1 border-r border-border bg-surface py-3"
      aria-label="Module shortcuts"
    >
      <div className="mb-2 flex h-7 w-7 items-center justify-center rounded bg-accent/15 text-xs font-bold text-accent">
        T
      </div>
      {NAV_ITEMS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          title={item.label}
          className={`flex h-8 w-8 items-center justify-center rounded ${
            isActive(pathname, item)
              ? "bg-surface-elevated text-foreground"
              : "text-muted hover:bg-surface-elevated hover:text-foreground"
          }`}
        >
          <Icon name={item.icon} />
        </Link>
      ))}
    </nav>
  );
}

/** Collapsible labeled sidebar. */
export function Sidebar({ open }: { open: boolean }) {
  const pathname = usePathname();
  if (!open) {
    return null;
  }
  const sections: NavItem["section"][] = ["operate", "analyze", "system"];
  return (
    <nav
      className="hidden w-52 shrink-0 flex-col gap-4 overflow-y-auto border-r border-border bg-surface p-3 md:flex"
      aria-label="Primary navigation"
    >
      {sections.map((section) => (
        <div key={section}>
          <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-muted">
            {SECTION_LABELS[section]}
          </p>
          <ul className="flex flex-col gap-0.5">
            {NAV_ITEMS.filter((item) => item.section === section).map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`flex items-center gap-2 rounded px-2 py-1.5 text-sm ${
                    isActive(pathname, item)
                      ? "bg-surface-elevated text-foreground"
                      : "text-muted hover:bg-surface-elevated hover:text-foreground"
                  }`}
                >
                  <Icon name={item.icon} className="h-3.5 w-3.5" />
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
