/**
 * The Playwright walk (M7): define → run → report.
 *
 * One test, deliberately. This is not a unit suite for the components — it is
 * the claim that the three views are a working path through the system, driven
 * the way a researcher drives it. Anything smaller could pass while the app was
 * unusable.
 *
 * It runs against the API backed by the in-memory ADP double
 * (`scripts/dev-server.py`), which is what makes it runnable in CI. That is
 * evidence the three views work; it is not evidence that a real study runs.
 * That claim belongs to gate G1 — see docs/blockers.md.
 */

import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const SMOKE = readFileSync(
  fileURLToPath(new URL("../../examples/smoke/study.yaml", import.meta.url)),
  "utf8",
);

test("define, run and analyze the smoke study", async ({ page }) => {
  await page.goto("/");

  // --- define ---------------------------------------------------------------
  await page.getByTestId("study-source").fill(SMOKE);
  await expect(page.getByTestId("validation-ok")).toBeVisible();

  // The digest is shown before anything is stored: a researcher should see the
  // identity of what they are about to run.
  const digest = await page.getByTestId("digest").innerText();
  expect(digest).toMatch(/^sha256:[0-9a-f]{64}$/);

  await page.getByTestId("store-study").click();
  await expect(page.getByTestId("selected-digest")).toHaveText(digest);

  // --- monitor --------------------------------------------------------------
  await expect(page.getByTestId("trial-grid")).toBeVisible();
  const cells = page.getByTestId(/^cell-/);
  await expect(cells).toHaveCount(8);

  await page.getByTestId("run-study").click();

  // Filled in by SSE as trials finish, not by polling the whole grid.
  await expect(page.getByTestId("cell-verified")).toHaveCount(8, { timeout: 90_000 });
  await expect(page.getByTestId("progress")).toContainText("8/8");

  // --- analyze --------------------------------------------------------------
  await page.getByTestId("go-analyze").click();
  await expect(page.getByTestId("axis-acceptance")).toBeVisible();

  // The noise floor is on the page before any contrast, which is the order the
  // report argues in.
  const noise = await page.getByTestId("noise-acceptance").innerText();
  expect(noise).toMatch(/Noise floor/);

  // Nothing blended: there is no composite anywhere in the analyze view.
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/composite|overall score/i);
});

test("a study that does not validate cannot be stored", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("study-source").fill("title: nothing else\n");

  await expect(page.getByTestId("validation-error")).toBeVisible();
  await expect(page.getByTestId("store-study")).toBeDisabled();
});
