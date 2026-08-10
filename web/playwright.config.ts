import { defineConfig } from "@playwright/test";

/**
 * The walk (M7): define → run → report, against a real server.
 *
 * `DUVA_API` points at a duva-bench server. With `DUVA_LIVE=1` that server is
 * expected to hold real ADP credentials and the walk runs the smoke study for
 * real; without it, the server is started with the in-memory ADP double from
 * `tests/fakes.py`, which is what CI uses. Both drive the same UI through the
 * same API — the difference is only what is behind the server.
 */
export default defineConfig({
  testDir: "tests",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.DUVA_WEB ?? "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    // An escape hatch for machines that already have a Chromium and no way to
    // download another one — a sandboxed CI image, most often. Unset, Playwright
    // uses the browser it manages itself.
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM }
      : {},
  },
  webServer: [
    {
      // The API. `scripts/dev-server.py` chooses the real ADP or the double
      // based on DUVA_LIVE, so this file does not need to know.
      // DUVA_PY lets a checkout point at a virtualenv without the config
      // knowing where anybody keeps theirs.
      command: `${process.env.DUVA_PY ?? "python3"} ../scripts/dev-server.py`,
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // `preview` passes `--host 127.0.0.1` rather than taking Vite's default,
      // and that is load-bearing: the default host is the *name* `localhost`,
      // which Node 17+ resolves to `::1` first. On a runner with IPv6 the
      // preview server then listens on `::1` only, this probe polls
      // `127.0.0.1` forever, and the job dies at the timeout below with no
      // failing test to point at — which is exactly how this passed locally
      // and failed in CI. Pin both ends to the same address family.
      command: "npm run build && npm run preview",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
