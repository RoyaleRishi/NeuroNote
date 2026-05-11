import { useEffect, type RefObject } from "react";

/**
 * Closes a popover/menu/panel when the user presses Escape or clicks outside
 * of `containerRef`.  No-op while `enabled` is false so the consumer can
 * conditionally mount the listener (e.g. only while the menu is open).
 */
export function useDismissable(
  containerRef: RefObject<HTMLElement | null>,
  enabled: boolean,
  onDismiss: () => void,
): void {
  useEffect(() => {
    if (!enabled) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onDismiss();
    }
    function onMouseDown(e: MouseEvent) {
      const el = containerRef.current;
      if (el && !el.contains(e.target as Node)) onDismiss();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onMouseDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onMouseDown);
    };
  }, [enabled, onDismiss, containerRef]);
}
