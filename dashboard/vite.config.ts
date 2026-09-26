/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// ADR 0008: OpenEMR serves the built app from public/dashboard/, same origin as the FHIR API.
// `npm run build:watch` writes straight into that bind-mounted folder during development.
export default defineConfig({
  base: "/public/dashboard/",
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../public/dashboard", import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
