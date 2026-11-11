import { defineConfig } from "@playwright/test";
import { join } from "node:path";
const installedOutput = process.env.SPOQ_VIEWER_OUT;
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  outputDir: installedOutput
    ? join(installedOutput, "playwright")
    : "test-results",
  reporter: [
    ["list"],
    [
      "json",
      {
        outputFile: installedOutput
          ? join(installedOutput, "playwright-results.json")
          : "test-results/results.json",
      },
    ],
  ],
  use: {
    baseURL: "http://127.0.0.1:4173",
    headless: true,
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: process.env.SPOQ_VIEWER_CONTROL_URL
    ? undefined
    : {
        command: "npm run dev -- --host 127.0.0.1 --port 4173 --strictPort",
        url: "http://127.0.0.1:4173",
        reuseExistingServer: false,
        timeout: 30000,
      },
});
