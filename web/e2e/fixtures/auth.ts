import type { Page } from "@playwright/test";

/**
 * API origin where auth cookies live. The web app talks to the API on
 * localhost:8000 with `credentials: 'include'`, and the API sets
 * `neuronote_access` + `neuronote_refresh` as httpOnly cookies scoped to
 * that origin. We log in by hitting the API directly through the page's
 * request context so the cookies land in the browser's cookie jar; they
 * will then be sent on subsequent XHRs from localhost:3000 -> localhost:8000.
 */
const API_BASE_URL = process.env.E2E_API_BASE_URL ?? "http://localhost:8000";

/**
 * Logs in as the canned dev user (`dev@neuronote.local`) via
 * `POST /v1/auth/dev/login`, then navigates to `/` and waits for the
 * workspace shell to render.
 *
 * Note: the dev tenant is reused across runs; state accumulates. A future
 * fixture should tear down the tenant for tests that need a clean slate.
 */
export async function loginAsDev(page: Page): Promise<void> {
  const response = await page.request.post(`${API_BASE_URL}/v1/auth/dev/login`);
  if (!response.ok()) {
    throw new Error(
      `dev login failed: ${response.status()} ${await response.text()}`,
    );
  }

  // Pin LLM mode to cloud so the EdgeConsentDialog — which renders as a
  // full-screen scrim and intercepts pointer events on every other control —
  // is never shown for tests that don't explicitly need it.  The edge-mode
  // consent test snapshots and restores this value itself.
  await page.request.put(`${API_BASE_URL}/v1/preferences`, {
    data: { llm_mode: "cloud" },
  });

  await page.goto("/");
  // The workspace shell renders a [data-testid="notes-workspace"] section
  // once `useAuth` has confirmed the session. If the cookie didn't make it,
  // the page would hard-redirect to /login and this selector would never
  // appear.
  await page.waitForSelector('[data-testid="notes-workspace"]', {
    state: "visible",
  });
}
