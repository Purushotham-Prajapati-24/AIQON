import { defineConfig, devices } from "@playwright/test";

// End-to-end checks against the production build, served by `vite preview`.
// Locally `PW_CHANNEL=msedge` (or chrome) reuses an installed browser; CI installs Chromium.
const PORT = 4174;
const channel = process.env.PW_CHANNEL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  // Locally, 10+ browsers loading a fresh build at once can stall `vite preview` for 15-20 s
  // (first reads of newly written dist/ files), which looks like an app hang. CI keeps the default.
  workers: process.env.CI ? undefined : 5,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    ...(channel ? { channel } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: {
    command: `npm run preview -- --port ${PORT} --strictPort --host 127.0.0.1`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
