import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import { API_BASE_URL, createNote, deleteNote, uniqueTitle } from "./fixtures/notes";

/**
 * Flow 12 — multi-select + bulk delete.
 *
 * Enter selection mode, tick the checkbox on two of three created notes,
 * trigger Delete in the bulk action bar, confirm the dialog, and assert
 * the two notes disappear from the sidebar while the third remains.
 */
test.describe("multi-select bulk delete", () => {
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

  test("deletes selected notes via the bulk action bar", async ({ page }) => {
    const titles = [uniqueTitle("ms-a"), uniqueTitle("ms-b"), uniqueTitle("ms-c")];
    for (const t of titles) {
      createdIds.push(await createNote(page.request, { title: t, content_text: t }));
    }

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    // Enter selection mode.
    await page.getByRole("button", { name: /^Select$/ }).click();

    // Tick the first two created notes.  The checkbox is aria-labelled
    // `Select <title>` by the workspace renderer.
    await page.getByRole("checkbox", { name: `Select ${titles[0]}` }).check();
    await page.getByRole("checkbox", { name: `Select ${titles[1]}` }).check();

    // The bulk action bar's Delete button.  There are multiple "Delete"
    // controls on the page (the per-note context menu, the confirm dialog);
    // scope to the action bar to keep selectors specific.
    await page.locator(".bulk-actions-bar").getByRole("button", { name: "Delete" }).click();

    // Confirm dialog.  ConfirmDialog renders the "Delete" action as a
    // danger-variant button inside a role=dialog.
    const confirm = page.getByRole("dialog", { name: /Delete notes/i });
    await expect(confirm).toBeVisible({ timeout: 5_000 });
    await confirm.getByRole("button", { name: "Delete" }).click();

    // Poll until both deleted notes are gone server-side.  handleBulkDelete
    // fires the DELETEs sequentially and isn't awaited by the confirm
    // handler, so a snapshot check races the network.
    await expect
      .poll(
        async () => {
          const r = await page.request.get(`${API_BASE_URL}/v1/notes?limit=200`);
          if (!r.ok()) return null;
          const body = (await r.json()) as { items: { note_title: string }[] };
          const titlesNow = body.items.map((n) => n.note_title);
          return {
            stillHasA: titlesNow.includes(titles[0]!),
            stillHasB: titlesNow.includes(titles[1]!),
            stillHasC: titlesNow.includes(titles[2]!),
          };
        },
        { timeout: 30_000, intervals: [500] },
      )
      .toEqual({ stillHasA: false, stillHasB: false, stillHasC: true });

    // Update createdIds so afterEach only tries to delete what survives.
    createdIds = createdIds.filter((_, i) => i === 2);
  });
});
