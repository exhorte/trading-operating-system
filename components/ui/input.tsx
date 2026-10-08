import * as React from "react"
import { cn } from "cn"

/**
 * The text field of the app — also the single source of the look of native
 * `select` and `input[type=date]` (see `fieldClass`), so a form never mixes
 * two kinds of field.
 */
export const fieldClass =
  "flex h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs transition-[color,box-shadow,border-color] outline-none placeholder:text-muted-foreground/80 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 aria-invalid:border-destructive aria-invalid:ring-destructive/20 disabled:cursor-not-allowed disabled:opacity-50 file:border-0 file:bg-transparent file:text-sm file:font-medium"

/** The same field, compact and content-sized: the filters of the list screens (/journal, /analyse). */
export const filterFieldClass = cn(fieldClass, "h-9 w-auto")

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(fieldClass, className)}
      {...props}
    />
  )
}

export { Input }
