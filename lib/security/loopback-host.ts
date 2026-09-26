/**
 * I0 (2026-09-26): the cockpit answers only when it is addressed by a
 * loopback name. `next dev` is bound to 127.0.0.1 (package.json), which keeps
 * the LAN out; this check defeats DNS rebinding — a page on another site that
 * re-points its own name at 127.0.0.1 still sends that name as Host, and
 * would otherwise read the cockpit (and its token route) as same-origin.
 *
 * Used by proxy.ts (Next 16's renamed middleware) on every request.
 */

const LOOPBACK_NAMES = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** True for `localhost`, `127.0.0.1` or `[::1]`, with or without a port. */
export function isLoopbackHost(host: string | null | undefined): boolean {
  if (!host) {
    return false;
  }
  const name = hostName(host.trim().toLowerCase());
  return name !== null && LOOPBACK_NAMES.has(name);
}

function hostName(host: string): string | null {
  if (host.startsWith("[")) {
    const end = host.indexOf("]");
    if (end < 0) {
      return null;
    }
    const rest = host.slice(end + 1);
    return rest === "" || /^:\d+$/.test(rest) ? host.slice(0, end + 1) : null;
  }
  const parts = host.split(":");
  if (parts.length > 2 || (parts.length === 2 && !/^\d+$/.test(parts[1]))) {
    return null;
  }
  return parts[0];
}
