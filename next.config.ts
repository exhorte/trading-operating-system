import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      // T12 incrément 2: /comptes (2026-09-21, read-only profile) became
      // /account. Temporary (307), not permanent: a browser caches a 308
      // forever, and this route has only ever existed on this machine.
      { source: "/comptes", destination: "/account", permanent: false },
    ];
  },
};

export default nextConfig;
