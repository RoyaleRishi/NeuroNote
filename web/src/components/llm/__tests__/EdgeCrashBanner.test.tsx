import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { EdgeCrashBanner } from "../EdgeCrashBanner";

describe("EdgeCrashBanner", () => {
  it("does not render when isOpen=false", () => {
    render(<EdgeCrashBanner isOpen={false} onAcknowledge={vi.fn()} />);
    expect(screen.queryByText(/didn't finish loading/i)).not.toBeInTheDocument();
  });

  it("renders all three actions when isOpen=true", () => {
    render(<EdgeCrashBanner isOpen onAcknowledge={vi.fn()} />);
    expect(screen.getByText(/didn't finish loading/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Switch to cloud/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Try on-device again/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dismiss/i })).toBeInTheDocument();
  });

  it("calls onAcknowledge('switchToCloud') when 'Switch to cloud' clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Switch to cloud/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("switchToCloud");
  });

  it("calls onAcknowledge('retry') when 'Try on-device again' clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Try on-device again/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("retry");
  });

  it("calls onAcknowledge('retry') when Dismiss (×) clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("retry");
  });
});
