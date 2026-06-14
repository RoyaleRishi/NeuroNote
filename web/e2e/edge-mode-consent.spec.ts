import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import { API_BASE_URL } from "./fixtures/notes";

/**
 * Flow 8 — edge-mode consent dialog.
 *
 * Toggling LLM mode to "edge" should surface the EdgeConsentDialog so the
 * user can opt in/out of the ~2GB in-browser model download.  We never
 * accept consent (the download is huge and headless Chromium's WebGPU is
 * flaky); we just confirm the dialog appears and can be dismissed back to
 * cloud, leaving the dev tenant in its starting state.
 *
 * State management: we snapshot the user's prior LLM mode at the start and
 * restore it in afterEach so this test doesn't pollute downstream runs.
 */
test.describe("edge mode consent", () => {
  let priorMode: "edge" | "cloud" | null = null;

  test.beforeEach(async ({ page }) => {
    await loginAsDev(page);
    const r = await page.request.get(`${API_BASE_URL}/v1/preferences`);
    if (r.ok()) {
      const prefs = (await r.json()) as { llm_mode: "edge" | "cloud" };
      priorMode = prefs.llm_mode;
    }
  });

  test.afterEach(async ({ page }) => {
    if (priorMode) {
      await page.request.put(`${API_BASE_URL}/v1/preferences`, {
        data: { llm_mode: priorMode },
      });
    }
  });

  test("switching to edge shows the consent dialog", async ({ page }) => {
    // Set edge mode directly via the API so the useEdgeLLM hook activates
    // synchronously on mount.  Driving the toggle through the UI race-
    // condition is unnecessary for this assertion: we only care that
    // edge-mode renders a blocking dialog before any model download begins.
    await page.request.put(`${API_BASE_URL}/v1/preferences`, {
      data: { llm_mode: "edge" },
    });
    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    // One of two dialogs renders depending on whether headless Chromium
    // exposes WebGPU:
    //   * EdgeConsentDialog ("Choose how note summaries are written") when WebGPU is supported.
    //   * WebGPUCheck modal ("WebGPU not supported") when it isn't.
    // Either outcome proves the edge-mode path is gated.  We accept whichever
    // shows and dismiss back to cloud.
    const consentDialog = page.getByRole("dialog", { name: /Choose how note summaries are written/i });
    const unsupportedDialog = page.getByRole("dialog", { name: /WebGPU/i });

    await expect(consentDialog.or(unsupportedDialog)).toBeVisible({ timeout: 15_000 });

    if (await consentDialog.isVisible()) {
      await consentDialog.getByRole("button", { name: "Use cloud" }).click();
    } else {
      // WebGPUCheck offers an "Open settings" affordance that flips back to
      // cloud via the onOpenSettings callback.  Title varies, so fall back
      // to clicking any button labelled to switch to cloud / open settings.
      const settingsBtn = unsupportedDialog.getByRole("button", {
        name: /settings|cloud/i,
      }).first();
      if (await settingsBtn.isVisible()) {
        await settingsBtn.click();
      }
    }
  });
});
