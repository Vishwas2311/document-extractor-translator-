import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Deliberately isolated from vite.config.ts: that config wires vinext() and the
// Cloudflare Workers plugin (D1/R2 bindings, wrangler) for the app's RSC pipeline,
// which unit tests have no business booting. This config only needs plain React +
// jsdom to exercise pure functions and hooks.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    exclude: ["tests/rendered-html.test.mjs"],
    setupFiles: ["./tests/setup.ts"],
  },
});
