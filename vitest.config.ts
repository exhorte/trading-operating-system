import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Mirrors the tsconfig `@/*` path alias so tests import the same way app code does.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    include: ["lib/**/*.test.ts"],
    environment: "node",
  },
});
