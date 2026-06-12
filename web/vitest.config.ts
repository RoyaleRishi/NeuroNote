import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Keep Playwright e2e specs (web/e2e/**) out of the Vitest run.
    exclude: ["node_modules/**", "dist/**", ".next/**", "e2e/**"],
  },
});
