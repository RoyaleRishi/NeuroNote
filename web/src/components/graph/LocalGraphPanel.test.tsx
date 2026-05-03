import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LocalGraphPanel } from "./LocalGraphPanel";

describe("LocalGraphPanel", () => {
  it("renders loading state", () => {
    render(
      <LocalGraphPanel
        noteId="note-1"
        baseUrl="http://localhost:8000"
        graph={null}
        isLoading
        errorMessage={null}
        onRetry={() => {}}
        onOpenNote={() => {}}
      />,
    );
    expect(document.querySelector(".skeleton-graph")).toBeInTheDocument();
  });

  it("renders error state and retries", () => {
    const onRetry = vi.fn();
    render(
      <LocalGraphPanel
        noteId="note-1"
        baseUrl="http://localhost:8000"
        graph={null}
        isLoading={false}
        errorMessage="Failed to load local graph"
        onRetry={onRetry}
        onOpenNote={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders graph canvas and stats footer without filter controls", () => {
    render(
      <LocalGraphPanel
        noteId="note-1"
        baseUrl="http://localhost:8000"
        graph={{
          nodes: [
            { id: "note-1", type: "note", label: "Note 1", confidence: null, source_note_id: "note-1", metadata: {} },
            { id: "note-2", type: "note", label: "Note 2", confidence: null, source_note_id: "note-2", metadata: {} },
          ],
          edges: [
            { id: "edge-1", source: "note-1", target: "note-2", type: "LINKS_TO", confidence: 1, source_note_id: "note-1" },
          ],
          meta: {
            root_note_id: "note-1",
            applied_filters: { max_hops: 1, limit_nodes: 80, min_confidence: 0.9, include_types: ["note", "entity"] },
            truncated: false,
          },
        }}
        isLoading={false}
        errorMessage={null}
        onRetry={() => {}}
        onOpenNote={() => {}}
      />,
    );
    expect(screen.getByLabelText("Local graph canvas")).toBeInTheDocument();
    expect(screen.getByText("2 nodes · 1 edges")).toBeInTheDocument();
    // No filter controls
    expect(screen.queryByLabelText("Graph depth")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Minimum confidence")).not.toBeInTheDocument();
    expect(screen.queryByRole("listbox", { name: "Local graph nodes" })).not.toBeInTheDocument();
  });
});
