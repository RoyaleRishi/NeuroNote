import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GlobalGraphPanel } from "./GlobalGraphPanel";

const emptyGraph = {
  nodes: [],
  edges: [],
  meta: {
    total_notes: 0,
    applied_filters: { limit_nodes: 500, node_salience_threshold: 0.5, relationship_confidence_threshold: 0.5, include_types: ["note", "entity"] },
    truncated: false,
  },
};

describe("GlobalGraphPanel", () => {
  it("renders subject filter with options visible on focus", () => {
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={["math", "physics"]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={() => {}}
        onOpenNote={() => {}}
      />,
    );
    const input = screen.getByLabelText("Subject") as HTMLInputElement;
    expect(input.value).toBe("");
    fireEvent.focus(input);
    expect(screen.getByText("math")).toBeInTheDocument();
    expect(screen.getByText("physics")).toBeInTheDocument();
  });

  it("calls onFiltersChange with subject_id when subject is typed", () => {
    const onFiltersChange = vi.fn();
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={["math", "physics"]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={onFiltersChange}
        onOpenNote={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "math" } });
    expect(onFiltersChange).toHaveBeenCalledWith({ subject_id: "math" });
  });

  it("renders tag filter and calls onFiltersChange when tag is typed", () => {
    const onFiltersChange = vi.fn();
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={[]}
        availableTags={["lecture", "research"]}
        onRetry={() => {}}
        onFiltersChange={onFiltersChange}
        onOpenNote={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Tag"), { target: { value: "lecture" } });
    expect(onFiltersChange).toHaveBeenCalledWith({ tag: "lecture" });
  });

  it("renders node/edge counts as stat chips", () => {
    const graph = {
      nodes: [
        { id: "a", label: "A", type: "note", metadata: {} },
        { id: "b", label: "B", type: "entity", metadata: {} },
        { id: "c", label: "C", type: "entity", metadata: {} },
      ],
      edges: [{ source: "a", target: "b" }],
      meta: emptyGraph.meta,
    } as unknown as Parameters<typeof GlobalGraphPanel>[0]["graph"];
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={graph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={[]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={() => {}}
        onOpenNote={() => {}}
      />,
    );
    // Stat chips carry the labels and computed counts.
    expect(screen.getByText("Nodes")).toBeInTheDocument();
    expect(screen.getByText("Edges")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("offers a create action in the empty state when onCreateNote is provided", () => {
    const onCreateNote = vi.fn();
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={[]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={() => {}}
        onOpenNote={() => {}}
        onCreateNote={onCreateNote}
      />,
    );
    const button = screen.getByRole("button", { name: "Create note" });
    fireEvent.click(button);
    expect(onCreateNote).toHaveBeenCalledTimes(1);
  });

  it("renders the relationship legend and reflects show/hide toggles", () => {
    const graph = {
      nodes: [
        { id: "a", label: "A", type: "entity", confidence: null, source_note_id: null, metadata: {} },
        { id: "b", label: "B", type: "entity", confidence: null, source_note_id: null, metadata: {} },
      ],
      edges: [{ id: "e", source: "a", target: "b", type: "IS_A", confidence: 1, source_note_id: null }],
      meta: emptyGraph.meta,
    } as unknown as Parameters<typeof GlobalGraphPanel>[0]["graph"];
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={graph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={[]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={() => {}}
        onOpenNote={() => {}}
      />,
    );
    expect(screen.getByRole("region", { name: /relationship/i })).toBeInTheDocument();
    const checkbox = screen.getByRole("checkbox", { name: /show is a/i }) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    fireEvent.click(checkbox);
    expect(checkbox.checked).toBe(false);
  });

  it("does not render confidence slider or type checkboxes", () => {
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={[]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={() => {}}
        onOpenNote={() => {}}
      />,
    );
    expect(screen.queryByLabelText("Minimum confidence")).not.toBeInTheDocument();
    expect(screen.queryByText("Include")).not.toBeInTheDocument();
  });
});
