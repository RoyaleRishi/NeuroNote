import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { EdgeConsentDialog } from "../EdgeConsentDialog";

describe("EdgeConsentDialog", () => {
  it("does not render when isOpen=false", () => {
    render(
      <EdgeConsentDialog
        isOpen={false}
        onAccept={vi.fn()}
        onDecline={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Choose how note summaries are written/i)).not.toBeInTheDocument();
  });

  it("renders both options when isOpen=true", () => {
    render(
      <EdgeConsentDialog
        isOpen
        onAccept={vi.fn()}
        onDecline={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText(/Choose how note summaries are written/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use on-device/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use cloud/i })).toBeInTheDocument();
  });

  it("calls onAccept when 'Use on-device' is clicked", () => {
    const onAccept = vi.fn();
    render(
      <EdgeConsentDialog
        isOpen
        onAccept={onAccept}
        onDecline={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Use on-device/i }));
    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it("calls onDecline when 'Use cloud' is clicked", () => {
    const onDecline = vi.fn();
    render(
      <EdgeConsentDialog
        isOpen
        onAccept={vi.fn()}
        onDecline={onDecline}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Use cloud/i }));
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  it("calls onDismiss when Escape is pressed", () => {
    const onDismiss = vi.fn();
    render(
      <EdgeConsentDialog
        isOpen
        onAccept={vi.fn()}
        onDecline={vi.fn()}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
