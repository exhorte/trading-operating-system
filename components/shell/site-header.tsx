"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { AccountMenu } from "./account-menu";
import { LogoMark } from "./logo";
import { MobileNav } from "./mobile-nav";
import { navEntryFor, SECTION_LABELS } from "./nav";
import { ThemeToggle } from "./theme-toggle";

/**
 * The top bar: on the left (desktop) where the screen sits in the navigation,
 * on the right the account — who, which firm, which environment, with a
 * status dot on the avatar and the link details behind it — then the theme
 * switch and, below `lg`, the drawer. Everything that used to crowd it lives
 * where it is read (ADR 0012): compliance in the Command Center, news and the
 * emergency stop in the sidebar.
 */
export function SiteHeader() {
  const pathname = usePathname();
  const entry = navEntryFor(pathname);

  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 px-4 backdrop-blur-md sm:px-6 lg:px-10">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-3">
        <Link href="/" className="rounded-full lg:hidden" aria-label="Trading OS — Command Center">
          <LogoMark />
        </Link>
        <div className="hidden min-w-0 flex-1 items-center lg:flex">
          {entry && (
            <p className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
              <span>{SECTION_LABELS[entry.section]}</span>
              <ChevronRight className="size-3.5 shrink-0" aria-hidden="true" />
              <span className="min-w-0 truncate text-foreground">{entry.label}</span>
            </p>
          )}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <AccountMenu />
          <ThemeToggle />
          <MobileNav />
        </div>
      </div>
    </header>
  );
}
