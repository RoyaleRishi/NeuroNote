import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { ConceptInsightPanel } from "./ConceptInsightPanel";
import type { LocalGraphNode } from "../../../../shared/contracts/ts/v1/graph";

vi.mock("../../lib/api-client", () => ({
  fetchConceptInsight: vi.fn(),
}));
import { fetchConceptInsight } from "../../lib/api-client";

const node: LocalGraphNode = {
  id: "n",
  type: "concept",
  label: "machine learning",
  confidence: null,
  source_note_id: null,
  metadata: {},
};

describe("ConceptInsightPanel — insight_error UX", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the insight_error string when LLM call fails", async () => {
    (fetchConceptInsight as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      concept_label: "machine learning",
      notes_found: 1,
      note_refs: [{ note_id: "n1", note_title: "n", snippet: "..." }],
      insight: null,
      insight_error: "model: claude-3-5-haiku-latest not found",
      learning_links: [],
      generated_at: "2026-05-10T00:00:00Z",
    });

    render(
      <ConceptInsightPanel
        node={node}
        baseUrl="http://localhost:8000"
        onClose={() => {}}
        onOpenNote={() => {}}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/claude-3-5-haiku-latest not found/),
      ).toBeInTheDocument(),
    );
    // The misleading "Set LLM_API_KEY" copy must NOT appear when there is
    // a concrete error to show.
    expect(screen.queryByText(/Set/)).not.toBeInTheDocument();
  });

  it("falls back to no-key copy only when insight_error is null", async () => {
    (fetchConceptInsight as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      concept_label: "machine learning",
      notes_found: 1,
      note_refs: [{ note_id: "n1", note_title: "n", snippet: "..." }],
      insight: null,
      insight_error: null,
      learning_links: [],
      generated_at: "2026-05-10T00:00:00Z",
    });

    render(
      <ConceptInsightPanel
        node={node}
        baseUrl="http://localhost:8000"
        onClose={() => {}}
        onOpenNote={() => {}}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Configure a cloud AI key/i),
      ).toBeInTheDocument(),
    );
  });
});
