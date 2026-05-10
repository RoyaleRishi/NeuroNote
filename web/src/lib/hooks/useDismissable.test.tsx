import React, { useRef } from "react";
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useDismissable } from "./useDismissable";

function Fixture({ enabled, onDismiss }: { enabled: boolean; onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useDismissable(ref, enabled, onDismiss);
  return (
    <div>
      <div ref={ref} data-testid="inside">inside</div>
      <button data-testid="outside">outside</button>
    </div>
  );
}

describe("useDismissable", () => {
  it("calls onDismiss on Escape when enabled", () => {
    const onDismiss = vi.fn();
    render(<Fixture enabled={true} onDismiss={onDismiss} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("calls onDismiss on outside mousedown when enabled", () => {
    const onDismiss = vi.fn();
    const { getByTestId } = render(<Fixture enabled={true} onDismiss={onDismiss} />);
    fireEvent.mouseDown(getByTestId("outside"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("does not fire for clicks inside the ref", () => {
    const onDismiss = vi.fn();
    const { getByTestId } = render(<Fixture enabled={true} onDismiss={onDismiss} />);
    fireEvent.mouseDown(getByTestId("inside"));
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("is a no-op when disabled", () => {
    const onDismiss = vi.fn();
    render(<Fixture enabled={false} onDismiss={onDismiss} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
