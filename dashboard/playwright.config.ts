// Browser tests against the local dev stack (ADR 0007: Playwright on the host, never the stack's
// Selenium). The app under test is the build OpenEMR serves from public/dashboard/ (ADR 0008),
// so `npm run e2e` builds first. Local only: CI has no OpenEMR stack and runs Vitest alone.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  testMatch: /.*\.spec\.ts$/,
  // One worker: the legacy dashboard keeps its patient in the PHP session.
  workers: 1,
  fullyParallel: false,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
  use: {
    baseURL: process.env.OE_BASE_URL ?? "https://localhost:9300",
    ignoreHTTPSErrors: true, // the dev stack's certificate on 9300 is self-signed
    trace: "retain-on-failure",
  },
});
