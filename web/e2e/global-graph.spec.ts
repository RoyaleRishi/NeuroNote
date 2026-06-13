import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import { API_BASE_URL, createNote, deleteNote, uniqueTitle } from "./fixtures/notes";

/**
 * Flow 4 — global graph view.
 *
 * Creates one note with extractable content, waits for processing to land
 * (via the public processing-status API rather than polling the UI for the
 * badge — fewer moving parts), then opens the Graph tab and asserts the
 * D3 <svg> renders at least one node.
 */
test.describe("global graph", () => {
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

  test("graph tab renders nodes after a note exists", async ({ page }) => {
    const title = uniqueTitle("graph");
    const noteId = await createNote(page.request, {
      title,
      content_text:
        "Quantum computing relies on superposition. Qubits encode information. " +
        "Entanglement links qubits. Decoherence is a major challenge.",
    });
    createdIds.push(noteId);

    // Poll the global graph endpoint until at least one node lands.  This
    // sidesteps editor-mounting races and proves the data is server-side
    // ready before we drive the UI.
    await expect
      .poll(
        async () => {
          const r = await page.request.get(`${API_BASE_URL}/v1/graph/global`);
          if (!r.ok()) return 0;
          const body = await r.json();
          return Array.isArray(body.nodes) ? body.nodes.length : 0;
        },
        { timeout: 60_000, intervals: [1_000] },
      )
      .toBeGreaterThan(0);

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });
    // Two "Graph" tabs may render once a note is open (app-level + editor's
    // local-graph toggle).  Scope to the top-level "App view" tablist.
    await page.getByRole("tablist", { name: "App view" }).getByRole("tab", { name: "Graph" }).click();

    // The D3GraphCanvas renders an <svg>; nodes are <circle> or <g> children.
    // We only require *some* drawable child to confirm we left the loading
    // / empty state — the exact node shape is implementation detail.
    const svg = page.locator("svg").first();
    await expect(svg).toBeVisible({ timeout: 30_000 });
    await expect(svg.locator("circle")).not.toHaveCount(0, { timeout: 15_000 });
  });
});
