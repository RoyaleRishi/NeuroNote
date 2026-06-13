import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import { createNote, deleteNote, uniqueTitle } from "./fixtures/notes";

/**
 * Flow 6 — backlinks (linked mentions).
 *
 * Note A mentions Note B via a [[wiki-link]]; opening B's "Linked mentions"
 * dialog should list A as a source.  We rely on the editor's autosave
 * pipeline to register the link, then open the modal via the note-options
 * menu in the editor toolbar.
 */
test.describe("backlinks", () => {
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

  test("a note mentioning [[B]] appears in B's linked mentions", async ({ page }) => {
    const titleB = uniqueTitle("backlinks-target");
    const titleA = uniqueTitle("backlinks-source");

    // Create B first so the wiki-link target exists when A is processed.
    const idB = await createNote(page.request, {
      title: titleB,
      content_text: "Body of target note.",
    });
    createdIds.push(idB);

    const idA = await createNote(page.request, {
      title: titleA,
      content_text: `Linking to [[${titleB}]] here.`,
    });
    createdIds.push(idA);

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    // Open B in the editor.
    await page.getByRole("button", { name: titleB }).first().click();
    await expect(page.locator('[data-testid="tiptap-editor"]')).toBeVisible({ timeout: 15_000 });

    // Open the note-options menu and click "Linked mentions".
    await page.getByRole("button", { name: "Note options" }).click();
    await page.getByRole("button", { name: "Linked mentions" }).click();

    // The backlinks modal is labelled "Linked mentions".  We assert that
    // A's title appears in the list — backlink resolution may take several
    // seconds because it depends on the NLP pipeline finishing for A.
    const modal = page.getByRole("dialog", { name: /Linked mentions/i });
    await expect(modal).toBeVisible({ timeout: 15_000 });
    await expect(modal.getByText(titleA, { exact: false })).toBeVisible({
      timeout: 45_000,
    });
  });
});
