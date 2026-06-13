import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import { createNote, deleteNote, uniqueTitle } from "./fixtures/notes";

/**
 * Flow 10 — quick-switch modal.
 *
 * Cmd/Ctrl+K opens the quick switcher.  Typing a partial title narrows the
 * list; Enter activates the first match.  We assert the editor swaps to
 * the matched note by checking its title input.
 */
test.describe("quick switch", () => {
  let createdIds: string[] = [];

  test.beforeEach(async ({ page }) => {
    createdIds = [];
    await loginAsDev(page);
  });

  test.afterEach(async ({ page }) => {
    for (const id of createdIds) {
      await deleteNote(page.request, id);
    }
  });

  test("Cmd/Ctrl+K switches to a note matching the typed query", async ({ page }, testInfo) => {
    const titleA = uniqueTitle("qs-alpha");
    const titleB = uniqueTitle("qs-bravo");

    createdIds.push(
      await createNote(page.request, { title: titleA, content_text: "a" }),
      await createNote(page.request, { title: titleB, content_text: "b" }),
    );

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    // The shortcut keymap accepts both Meta+K (mac) and Ctrl+K (win/linux).
    const isMac = testInfo.project.use?.userAgent?.includes("Mac") ?? process.platform === "darwin";
    await page.keyboard.press(isMac ? "Meta+K" : "Control+K");

    const qsInput = page.getByRole("textbox", { name: "Quick switch" });
    await expect(qsInput).toBeVisible({ timeout: 5_000 });

    // Type enough of titleB to win the fuzzy filter.  The unique random
    // suffix on each title is the cheapest way to guarantee a single match.
    const fragment = titleB.split("-").slice(-1)[0] ?? titleB;
    await qsInput.fill(fragment);

    await page.keyboard.press("Enter");

    // The editor's title input reflects the selected note.
    const titleInput = page.getByRole("textbox", { name: "Note title" });
    await expect(titleInput).toHaveValue(titleB, { timeout: 15_000 });
  });
});
