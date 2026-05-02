import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { LiveConceptsPreview } from "../LiveConceptsPreview";

describe("LiveConceptsPreview", () => {
  it("renders nothing when concepts is empty", () => {
    const { container } = render(
      <LiveConceptsPreview concepts={[]} isProcessing />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows the count when concepts is non-empty", () => {
    render(
      <LiveConceptsPreview concepts={["a", "b", "c"]} isProcessing />,
    );
    expect(screen.getByRole("button")).toHaveTextContent("3 concepts found");
  });

  it("popover is closed by default — concepts not visible", () => {
    render(
      <LiveConceptsPreview concepts={["alpha", "beta"]} isProcessing />,
    );
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
    expect(screen.queryByText("beta")).not.toBeInTheDocument();
  });

  it("clicking the pill toggles the popover", () => {
    render(
      <LiveConceptsPreview concepts={["alpha", "beta"]} isProcessing />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button"));
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  });

  it("renders concepts in insertion order", () => {
    render(
      <LiveConceptsPreview concepts={["zeta", "alpha", "mu"]} isProcessing />,
    );
    fireEvent.click(screen.getByRole("button"));
    const items = screen.getAllByRole("listitem").map((el) => el.textContent);
    expect(items).toEqual(["zeta", "alpha", "mu"]);
  });
});
