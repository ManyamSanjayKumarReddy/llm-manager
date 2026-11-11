/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` proxies the API to a locally running backend (uvicorn on :8000).
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  // No inline assets: the page's CSP only allows files served from the same origin.
  build: { sourcemap: false, target: "es2022", assetsInlineLimit: 0 },
  server: {
    // Anchored patterns: a plain "/api" would also catch the dashboard's own /api-keys page.
    proxy: { "^/api/": backend, "^/v1/": backend, "^/healthz$": backend },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["tests/setup.ts"],
    css: false,
  },
});
