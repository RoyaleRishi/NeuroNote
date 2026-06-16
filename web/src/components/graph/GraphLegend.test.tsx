import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GraphLegend } from "./GraphLegend";

function setup(overrides: Partial<React.ComponentProps<typeof GraphLegend>> = {}) {
  const props: React.ComponentProps<typeof GraphLegend> = {
    presentTypes: ["IS_A", "SYNONYM_OF", "MENTIONED_TOGETHER", "LINKS_TO"],
    hidden: new Set<string>(),
    highlighted: new Set<string>(),
    onToggleHidden: vi.fn(),
    onToggleHighlighted: vi.fn(),
    ...overrides,
  };
  render(<GraphLegend {...props} />);
  return props;
}

describe("GraphLegend", () => {
  it("renders only the edge types present in the graph, with human names", () => {
    setup();
    expect(screen.getByText("is a")).toBeInTheDocument();
    expect(screen.getByText("synonym of")).toBeInTheDocument();
    expect(screen.getByText("mentioned together")).toBeInTheDocument();
    expect(screen.getByText("links to")).toBeInTheDocument();
    // A type not present should not appear.
    expect(screen.queryByText("defined by")).not.toBeInTheDocument();
  });

  it("is exposed as a labelled region", () => {
    setup();
    expect(screen.getByRole("region", { name: /relationship/i })).toBeInTheDocument();
  });

  it("calls onToggleHidden when a visibility checkbox is clicked", () => {
    const props = setup();
    const checkbox = screen.getByRole("checkbox", { name: /show is a/i });
    fireEvent.click(checkbox);
    expect(props.onToggleHidden).toHaveBeenCalledWith("IS_A");
  });

  it("reflects hidden state as an unchecked visibility checkbox", () => {
    setup({ hidden: new Set(["IS_A"]) });
    const checkbox = screen.getByRole("checkbox", { name: /show is a/i }) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });

  it("calls onToggleHighlighted when the highlight control is activated", () => {
    const props = setup();
    const btn = screen.getByRole("button", { name: /highlight is a/i });
    fireEvent.click(btn);
    expect(props.onToggleHighlighted).toHaveBeenCalledWith("IS_A");
  });

  it("reflects highlighted state via aria-pressed", () => {
    setup({ highlighted: new Set(["SYNONYM_OF"]) });
    const btn = screen.getByRole("button", { name: /highlight synonym of/i });
    expect(btn).toHaveAttribute("aria-pressed", "true");
  });

  it("activates highlight on keyboard Space", () => {
    const props = setup();
    const btn = screen.getByRole("button", { name: /highlight links to/i });
    btn.focus();
    fireEvent.keyDown(btn, { key: " " });
    expect(props.onToggleHighlighted).toHaveBeenCalledWith("LINKS_TO");
  });

  it("groups related types under a group heading", () => {
    setup();
    const region = screen.getByRole("region", { name: /relationship/i });
    // The hierarchy group heading is rendered.
    expect(within(region).getByText(/hierarchy/i)).toBeInTheDocument();
  });
});
