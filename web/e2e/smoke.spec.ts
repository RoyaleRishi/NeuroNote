import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";

test("dev login lands in workspace", async ({ page }) => {
  await loginAsDev(page);

  // The workspace shell is the canonical post-login surface. Asserting on
  // both the container and the sidebar header proves: (a) the auth cookie
  // travelled cross-origin to the API, (b) `useAuth` did NOT redirect to
  // /login, and (c) the NotesWorkspace mounted.
  const workspace = page.locator('[data-testid="notes-workspace"]');
  await expect(workspace).toBeVisible();
  await expect(workspace.locator("h1", { hasText: "Notes" })).toBeVisible();

  // Should not have been bounced to the login page.
  expect(page.url()).not.toContain("/login");
});
