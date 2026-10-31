import * as React from "react";
import { cn } from "cn";

/**
 * Table with a dark header (the `panel` surface). The rounded container
 * (border + overflow) clips the header corners, which `border-radius` on
 * cells would not guarantee with `border-collapse`. The dark band painted on
 * <table> (one header row tall) hides the thin light seams a browser leaves
 * between cells at fractional positions.
 *
 * The table scrolls INSIDE its container when it is wider than the screen —
 * never the page.
 */
function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div
      data-slot="table-container"
      className="relative w-full overflow-x-auto rounded-xl border bg-card shadow-xs"
    >
      <table
        data-slot="table"
        className={cn(
          "w-full caption-bottom text-sm",
          "bg-[linear-gradient(var(--panel),var(--panel))] bg-[length:100%_2.75rem] bg-top bg-no-repeat",
          className
        )}
        {...props}
      />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("bg-panel text-panel-foreground [&_tr]:border-0 [&_tr]:hover:bg-transparent", className)}
      {...props}
    />
  );
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return <tbody data-slot="table-body" className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn("border-b transition-colors hover:bg-muted/50", className)}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-11 px-4 text-left align-middle text-xs font-medium whitespace-nowrap text-panel-foreground/85",
        className
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn("px-4 py-3.5 align-middle whitespace-nowrap", className)}
      {...props}
    />
  );
}

export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell };
