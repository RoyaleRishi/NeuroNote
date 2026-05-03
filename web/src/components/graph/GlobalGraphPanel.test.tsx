import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GlobalGraphPanel } from "./GlobalGraphPanel";

const emptyGraph = {
  nodes: [],
  edges: [],
  meta: {
    total_notes: 0,
    applied_filters: { limit_nodes: 500, min_confidence: 0.9, include_types: ["note", "entity"] },
    truncated: false,
  },
};

describe("GlobalGraphPanel", () => {
  it("renders subject dropdown with all options and default empty selection", () => {
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
    const select = screen.getByLabelText("Filter by subject") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(screen.getByText("All subjects")).toBeInTheDocument();
    expect(screen.getByText("math")).toBeInTheDocument();
    expect(screen.getByText("physics")).toBeInTheDocument();
  });

  it("calls onFiltersChange with subject_id when subject is selected", () => {
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
    fireEvent.change(screen.getByLabelText("Filter by subject"), { target: { value: "math" } });
    expect(onFiltersChange).toHaveBeenCalledWith({ subject_id: "math" });
  });

  it("renders tag dropdown and calls onFiltersChange when tag selected", () => {
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
    fireEvent.change(screen.getByLabelText("Filter by tag"), { target: { value: "lecture" } });
    expect(onFiltersChange).toHaveBeenCalledWith({ tag: "lecture" });
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
