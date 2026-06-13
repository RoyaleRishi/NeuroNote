import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import { API_BASE_URL, deleteNote, uniqueTitle } from "./fixtures/notes";

/**
 * Flow 7 — markdown import.
 *
 * Two parts:
 *   (1) call POST /v1/notes/import directly with a small markdown blob
 *       and assert the response shape;
 *   (2) reload the workspace and assert the imported note appears in the
 *       sidebar.
 *
 * Direct API exercise is preferred over a synthetic drag-drop event because
 * Playwright's DataTransfer + FileReader handshake is fragile across builds,
 * and the FileDropZone's only responsibility is wiring the file content
 * into the same `importNote` call we make here.
 */
test.describe("markdown import", () => {
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

  test("POST /v1/notes/import surfaces the note in the sidebar", async ({ page }) => {
    const filenameBase = uniqueTitle("import");
    const filename = `${filenameBase}.md`;
    const content = [
      `# ${filenameBase}`,
      "",
      "First paragraph of an imported note.",
      "",
      "- bullet one",
      "- bullet two",
      "",
    ].join("\n");

    const response = await page.request.post(`${API_BASE_URL}/v1/notes/import`, {
      data: { filename, content },
    });
    expect(response.ok()).toBe(true);
    const body = (await response.json()) as { note_id: string; note_title: string };
    createdIds.push(body.note_id);
    expect(body.note_id).toBeTruthy();

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });

    // The title may be derived from the filename or H1 — both contain our
    // unique base.  A substring match is robust to either choice.
    const sidebar = page.locator(".notes-sidebar");
    await expect(sidebar.getByText(filenameBase, { exact: false }).first()).toBeVisible({
      timeout: 15_000,
    });
  });
});
