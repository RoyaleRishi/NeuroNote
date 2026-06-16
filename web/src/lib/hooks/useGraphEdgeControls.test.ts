import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useGraphEdgeControls } from "./useGraphEdgeControls";

describe("useGraphEdgeControls", () => {
  it("starts with nothing hidden or highlighted", () => {
    const { result } = renderHook(() => useGraphEdgeControls());
    expect(result.current.hidden.size).toBe(0);
    expect(result.current.highlighted.size).toBe(0);
  });

  it("toggleHidden adds then removes a type", () => {
    const { result } = renderHook(() => useGraphEdgeControls());
    act(() => result.current.toggleHidden("IS_A"));
    expect(result.current.hidden.has("IS_A")).toBe(true);
    act(() => result.current.toggleHidden("IS_A"));
    expect(result.current.hidden.has("IS_A")).toBe(false);
  });

  it("toggleHighlighted adds then removes a type", () => {
    const { result } = renderHook(() => useGraphEdgeControls());
    act(() => result.current.toggleHighlighted("SYNONYM_OF"));
    expect(result.current.highlighted.has("SYNONYM_OF")).toBe(true);
    act(() => result.current.toggleHighlighted("SYNONYM_OF"));
    expect(result.current.highlighted.has("SYNONYM_OF")).toBe(false);
  });

  it("reset clears both sets", () => {
    const { result } = renderHook(() => useGraphEdgeControls());
    act(() => {
      result.current.toggleHidden("IS_A");
      result.current.toggleHighlighted("MENTIONS");
    });
    act(() => result.current.reset());
    expect(result.current.hidden.size).toBe(0);
    expect(result.current.highlighted.size).toBe(0);
  });
});
