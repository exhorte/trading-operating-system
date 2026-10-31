import type { ReactNode } from "react";
import { cn } from "cn";

/**
 * The signature composition: content 3/5 on the left, dark metric panel 2/5
 * on the right.
 *
 * - explicit `grid-cols-1` below `lg`: without it the implicit column widens
 *   to its `nowrap` content and the page overflows on mobile;
 * - `min-w-0` on each column lets truncated text shrink;
 * - `stickyAside`: the panel stays in view while a long page scrolls
 *   (`top-24` = the 4 rem top bar + breathing room);
 * - `asideFirstOnMobile`: on mobile the key figures come BEFORE the detail.
 */
export function SplitLayout({
  main,
  aside,
  stickyAside = false,
  asideFirstOnMobile = false,
  className,
}: {
  main: ReactNode;
  aside: ReactNode;
  stickyAside?: boolean;
  asideFirstOnMobile?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("grid grid-cols-1 items-start gap-6 lg:grid-cols-5", className)}>
      <div className="flex min-w-0 flex-col gap-4 lg:col-span-3">{main}</div>
      <div
        className={cn(
          "flex min-w-0 flex-col gap-4 lg:col-span-2",
          stickyAside && "lg:sticky lg:top-24",
          asideFirstOnMobile && "order-first lg:order-none"
        )}
      >
        {aside}
      </div>
    </div>
  );
}
