/**
 * The backend's plain-HTTP base, derived from the same env var as the
 * SignalR hub URL (NEXT_PUBLIC_BACKEND_HUB_URL) — one source for both,
 * rather than every HTTP caller re-deriving it (T05: added a second
 * consumer, the journal capture viewer, alongside signalr-client.ts).
 */
export function backendHttpBase(): string {
  const hubUrl = process.env.NEXT_PUBLIC_BACKEND_HUB_URL ?? "http://localhost:5080/hub/cockpit";
  return hubUrl.replace(/\/hub\/cockpit\/?$/, "");
}
