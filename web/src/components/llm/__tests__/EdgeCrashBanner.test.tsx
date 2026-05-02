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
    expect(screen.getByRole("button", { name: /Switch to Cloud AI/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Try Edge AI again/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dismiss/i })).toBeInTheDocument();
  });

  it("calls onAcknowledge('switchToCloud') when 'Switch to Cloud AI' clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Switch to Cloud AI/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("switchToCloud");
  });

  it("calls onAcknowledge('retry') when 'Try Edge AI again' clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Try Edge AI again/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("retry");
  });

  it("calls onAcknowledge('retry') when Dismiss (×) clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("retry");
  });
});
