import { expect, test } from "@playwright/test";
import { loginAsDev } from "./fixtures/auth";
import {
  API_BASE_URL,
  createNote,
  deleteNote,
  processNoteAndWait,
  randomSuffix,
  uniqueTitle,
} from "./fixtures/notes";

/**
 * Flow 5 — concept insight panel.
 *
 * Creates a note with a distinctive concept token, waits for the concept
 * to land in the registry, then opens the global graph and clicks the
 * matching node.  The panel should open with a "Related notes" section
 * listing our note.  The LLM-generated `insight` body may be absent (edge
 * mode, missing key) — that's tolerated.
 *
 * We click the node via its rendered text in the SVG.  D3GraphCanvas
 * draws each label as an <svg:text>.
 */
test.describe("concept insight panel", () => {
  let createdIds: string[] = [];

  // NLP pipeline + concept-insight LLM call may exceed the default 30s.
  test.setTimeout(180_000);

  test.beforeEach(async ({ page }) => {
    createdIds = [];
    await loginAsDev(page);
  });

  test.afterEach(async ({ page }) => {
    for (const id of createdIds) {
      await deleteNote(page.request, id);
    }
  });

  test("clicking a concept node opens the insight panel", async ({ page }) => {
    // A multi-word, capitalised, low-collision phrase — kbir-inspec readily
    // picks it up as a single concept and YAKE backs it as a fallback.
    const concept = `Photonic Lattice ${randomSuffix()}`;
    const title = uniqueTitle("insight");
    const body =
      `${concept} arrays exhibit topological edge modes. ` +
      `${concept} research draws on condensed matter physics. ` +
      `Experiments confirm ${concept} band structure predictions.`;
    const noteId = await createNote(page.request, { title, content_text: body });
    createdIds.push(noteId);

    // PUT /v1/notes does not auto-trigger extraction.  Drive the pipeline
    // explicitly and wait for completion so the concept lands in the graph.
    await processNoteAndWait(page.request, noteId, body);

    // Wait until the concept shows up in the global graph payload.
    await expect
      .poll(
        async () => {
          const r = await page.request.get(`${API_BASE_URL}/v1/graph/global`);
          if (!r.ok()) return false;
          const body = await r.json();
          if (!Array.isArray(body.nodes)) return false;
          return body.nodes.some((n: { label?: string }) =>
            typeof n.label === "string" && n.label.toLowerCase().includes("photonic lattice"),
          );
        },
        { timeout: 60_000, intervals: [1_500] },
      )
      .toBe(true);

    await page.reload();
    await page.waitForSelector('[data-testid="notes-workspace"]', { state: "visible" });
    await page.getByRole("tablist", { name: "App view" }).getByRole("tab", { name: "Graph" }).click();

    // Use the sidebar search input to highlight + zoom to the concept node,
    // then click the matching <text> label.  This is more reliable than
    // hunting through a force-directed layout.
    await page.getByRole("textbox", { name: "Search nodes" }).fill("Photonic Lattice");

    // The click handler is bound to the <g class="node"> group; the <text>
    // child has pointer-events: none.  Locate the group containing our label
    // and click its <circle>, which receives pointer events directly.
    const nodeGroup = page
      .locator("svg g.node")
      .filter({ has: page.locator("text", { hasText: /Photonic Lattice/i }) })
      .first();
    await expect(nodeGroup).toBeVisible({ timeout: 30_000 });
    await nodeGroup.locator("circle").click({ force: true });

    // ConceptInsightPanel opens as a role=dialog.  We assert the dialog
    // opens and shows the Related notes section — the LLM insight is
    // best-effort and may be absent.
    const panel = page.getByRole("dialog", { name: /Insight:/i });
    await expect(panel).toBeVisible({ timeout: 30_000 });
    await expect(panel.getByRole("heading", { name: /Related notes/i })).toBeVisible();
  });
});
