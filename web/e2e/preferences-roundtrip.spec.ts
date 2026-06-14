import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import { API_BASE_URL } from "./fixtures/notes";

/**
 * Flow 9 — preferences round-trip.
 *
 * Set a test value for `llm_model` via the user menu, reload, and verify
 * the value persists.  We exercise the UI form (not the API directly) so
 * the test covers the round trip through `updatePreferences` → backend
 * → `usePreferences` rehydration.
 *
 * Saved value uses a unique-per-run suffix so concurrent runs don't fight,
 * and we restore the prior value in afterEach.
 */
test.describe("preferences round-trip", () => {
  let priorModel: string | null = null;
  let priorBaseUrl: string | null = null;
  let priorMode: "edge" | "cloud" | null = null;

  test.beforeEach(async ({ page }) => {
    await loginAsDev(page);
    const r = await page.request.get(`${API_BASE_URL}/v1/preferences`);
    if (r.ok()) {
      const prefs = (await r.json()) as {
        llm_model: string;
        llm_base_url: string;
        llm_mode: "edge" | "cloud";
      };
      priorModel = prefs.llm_model;
      priorBaseUrl = prefs.llm_base_url;
      priorMode = prefs.llm_mode;
    }
  });

  test.afterEach(async ({ page }) => {
    if (priorModel !== null && priorBaseUrl !== null && priorMode !== null) {
      await page.request.put(`${API_BASE_URL}/v1/preferences`, {
        data: {
          llm_model: priorModel,
          llm_base_url: priorBaseUrl,
          llm_mode: priorMode,
        },
      });
    }
  });

  test("a saved llm_model survives a reload", async ({ page }) => {
    const stamp = `e2e-${Date.now().toString(36)}`;
    const testModel = `gpt-4o-mini-${stamp}`;

    // Force cloud mode so the cloud fields render in the user menu.
    await page.request.put(`${API_BASE_URL}/v1/preferences`, {
      data: { llm_mode: "cloud" },
    });
    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    await page.getByRole("button", { name: "Open settings" }).click();

    // The Model input has aria-label="Model".
    const modelInput = page.getByRole("textbox", { name: "Model" });
    await expect(modelInput).toBeVisible({ timeout: 5_000 });
    await modelInput.fill(testModel);

    // Save.  The handler validates via test-connection — we don't care if
    // that succeeds; we only care that the PUT lands.
    await page.getByRole("button", { name: /^Save$/ }).click();

    // Best signal that the PUT landed: read it back via API.  Polling the
    // UI label is brittle because the menu may auto-close on outside
    // mousedown during keyboard activity.
    await expect
      .poll(
        async () => {
          const r = await page.request.get(`${API_BASE_URL}/v1/preferences`);
          if (!r.ok()) return null;
          const body = (await r.json()) as { llm_model: string };
          return body.llm_model;
        },
        { timeout: 15_000, intervals: [500] },
      )
      .toBe(testModel);

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    await page.getByRole("button", { name: "Open settings" }).click();
    await expect(page.getByRole("textbox", { name: "Model" })).toHaveValue(testModel, {
      timeout: 10_000,
    });
  });

  test("saving cloud settings shows an immediate success toast (no reload)", async ({ page }) => {
    // Regression guard for the "no feedback until reload" bug: a preference
    // mutation must surface a toast in the same session, with no navigation.
    await page.request.put(`${API_BASE_URL}/v1/preferences`, {
      data: { llm_mode: "cloud" },
    });
    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    await page.getByRole("button", { name: "Open settings" }).click();
    const modelInput = page.getByRole("textbox", { name: "Model" });
    await expect(modelInput).toBeVisible({ timeout: 5_000 });
    await modelInput.fill("gpt-4o-mini");
    await page.getByRole("button", { name: /^Save$/ }).click();

    await expect(page.getByText("Cloud summary settings saved")).toBeVisible({ timeout: 10_000 });
  });
});
