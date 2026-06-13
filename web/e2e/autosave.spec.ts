import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import { createNote, deleteNote, uniqueTitle } from "./fixtures/notes";

/**
 * Flow 2 — autosave persistence.
 *
 * Creates a note, opens it in the editor, types content, lets the 800ms
 * debounce + a margin elapse, reloads, and asserts the typed text is
 * persisted server-side.  Proves the lifecycle controller's autosave
 * pipeline survives a hard reload.
 */
test.describe("autosave", () => {
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

  test("typed paragraph survives a reload", async ({ page }) => {
    const title = uniqueTitle("autosave");
    const noteId = await createNote(page.request, {
      title,
      content_text: " ",
    });
    createdIds.push(noteId);

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    // Pick the note from the sidebar by its unique title.
    await page.getByRole("button", { name: title }).first().click();

    // Editor mounts; focus the TipTap content area (contentEditable) and type.
    const editable = page.locator('[data-testid="tiptap-editor"] [contenteditable="true"]');
    await expect(editable).toBeVisible({ timeout: 15_000 });

    const sentinel = `autosave-sentinel-${Date.now()}`;
    await editable.click();
    await editable.focus();
    await page.keyboard.type(sentinel, { delay: 10 });

    // 800ms autosave debounce + margin for the PUT to land server-side.
    // Poll the API rather than guessing — that's the true persistence boundary.
    await expect
      .poll(
        async () => {
          const r = await page.request.get(
            `${process.env.E2E_API_BASE_URL ?? "http://localhost:8000"}/v1/notes/${noteId}`,
          );
          if (!r.ok()) return "";
          const body = (await r.json()) as { content_text: string };
          return body.content_text ?? "";
        },
        { timeout: 15_000, intervals: [500] },
      )
      .toContain(sentinel);

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });
    await page.getByRole("button", { name: title }).first().click();

    await expect(page.locator('[data-testid="tiptap-editor"]')).toContainText(
      sentinel,
      { timeout: 15_000 },
    );
  });
});
