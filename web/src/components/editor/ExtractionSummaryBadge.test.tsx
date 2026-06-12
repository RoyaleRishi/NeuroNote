import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { ExtractionSummaryBadge } from "./ExtractionSummaryBadge";
import type { ExtractionSummary } from "../../../../shared/contracts/ts/v1/process";

const SAMPLE_SUMMARY: ExtractionSummary = {
  entity_count: 5,
  relation_count: 3,
  top_entities: ["machine learning", "neural networks", "backpropagation"],
};

describe("ExtractionSummaryBadge", () => {
  it("renders nothing when summary is null", () => {
    const { container } = render(<ExtractionSummaryBadge summary={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders counts when summary is provided", () => {
    render(<ExtractionSummaryBadge summary={SAMPLE_SUMMARY} />);
    expect(screen.getByTestId("extraction-summary-badge")).toBeTruthy();
    expect(screen.getByText(/5 concepts/)).toBeTruthy();
    expect(screen.getByText(/3 relations/)).toBeTruthy();
  });

  it("renders top entity pills", () => {
    render(<ExtractionSummaryBadge summary={SAMPLE_SUMMARY} />);
    expect(screen.getByText("machine learning")).toBeTruthy();
    expect(screen.getByText("neural networks")).toBeTruthy();
    expect(screen.getByText("backpropagation")).toBeTruthy();
  });

  it("hides on click", async () => {
    render(<ExtractionSummaryBadge summary={SAMPLE_SUMMARY} />);
    const badge = screen.getByTestId("extraction-summary-badge");
    await act(async () => { badge.click(); });
    expect(screen.queryByTestId("extraction-summary-badge")).toBeNull();
  });

  it("auto-dismisses after timeout", () => {
    vi.useFakeTimers();
    render(<ExtractionSummaryBadge summary={SAMPLE_SUMMARY} autoDismissMs={1000} />);
    expect(screen.getByTestId("extraction-summary-badge")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(1100); });
    expect(screen.queryByTestId("extraction-summary-badge")).toBeNull();
    vi.useRealTimers();
  });

  it("handles singular counts correctly", () => {
    render(
      <ExtractionSummaryBadge
        summary={{ entity_count: 1, relation_count: 1, top_entities: [] }}
      />,
    );
    expect(screen.getByText(/1 concept/)).toBeTruthy();
    expect(screen.getByText(/1 relation(?!s)/)).toBeTruthy();
  });

  it("renders nothing when all counts are zero", () => {
    const { container } = render(
      <ExtractionSummaryBadge
        summary={{ entity_count: 0, relation_count: 0, top_entities: [] }}
      />,
    );
    expect(container.innerHTML).toBe("");
  });
});
