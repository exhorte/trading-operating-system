import { NextResponse, type NextRequest } from "next/server";
import { isLoopbackHost } from "@/lib/security/loopback-host";

/**
 * I0 (2026-09-26): every request, static assets included, must name the
 * cockpit by a loopback host — the DNS-rebinding guard (lib/security/
 * loopback-host.ts). `proxy` is Next 16's name for middleware
 * (node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md).
 */
export function proxy(request: NextRequest) {
  if (!isLoopbackHost(request.headers.get("host"))) {
    return new NextResponse("Host not allowed", { status: 403 });
  }
  return NextResponse.next();
}
