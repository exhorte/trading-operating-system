import { describe, expect, it } from "vitest";
import { isLoopbackHost } from "./loopback-host";

describe("isLoopbackHost (I0: DNS rebinding guard)", () => {
  it("accepts the loopback names, with or without a port", () => {
    for (const host of ["localhost", "localhost:3000", "127.0.0.1:3001", "127.0.0.1", "[::1]:3000", "[::1]", "LOCALHOST:3000"]) {
      expect(isLoopbackHost(host), host).toBe(true);
    }
  });

  it("refuses any other name — a rebinding page sends its own", () => {
    for (const host of [
      "evil.example:3000",
      "localhost.evil.example:3000",
      "127.0.0.1.nip.io:3000",
      "192.168.1.20:3000",
      "0.0.0.0:3000",
      "host.docker.internal:3000",
    ]) {
      expect(isLoopbackHost(host), host).toBe(false);
    }
  });

  it("refuses malformed or missing hosts", () => {
    for (const host of [null, undefined, "", "localhost:abc", "localhost:3000:1", "[::1", "[::1]x", "[::1]:"]) {
      expect(isLoopbackHost(host), String(host)).toBe(false);
    }
  });
});
