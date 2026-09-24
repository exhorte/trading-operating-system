import * as React from "react"

const MOBILE_BREAKPOINT = 768
const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

function subscribe(onChange: () => void) {
  const mql = window.matchMedia(QUERY)
  mql.addEventListener("change", onChange)
  return () => mql.removeEventListener("change", onChange)
}

/**
 * shadcn/ui's hook, rewritten on `useSyncExternalStore`: the generated
 * version set state inside an effect, which this repo's react-hooks rules
 * refuse (cascading renders). Same answer, subscribed the idiomatic way;
 * false on the server.
 */
export function useIsMobile() {
  return React.useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => false
  )
}
