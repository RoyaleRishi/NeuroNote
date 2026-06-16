import { useCallback, useState } from "react";

/**
 * Per-graph edge control state: which relationship types are hidden, and which
 * are highlighted. Each graph surface (local + global) owns its own instance.
 */
export interface GraphEdgeControls {
  /** Edge types the user has toggled *off* (hidden from the canvas). */
  hidden: Set<string>;
  /** Edge types the user has toggled to *highlight* (emphasised; others dim). */
  highlighted: Set<string>;
  toggleHidden: (type: string) => void;
  toggleHighlighted: (type: string) => void;
  reset: () => void;
}

function toggle(prev: Set<string>, type: string): Set<string> {
  const next = new Set(prev);
  if (next.has(type)) next.delete(type);
  else next.add(type);
  return next;
}

export function useGraphEdgeControls(): GraphEdgeControls {
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [highlighted, setHighlighted] = useState<Set<string>>(() => new Set());

  const toggleHidden = useCallback((type: string) => setHidden((p) => toggle(p, type)), []);
  const toggleHighlighted = useCallback(
    (type: string) => setHighlighted((p) => toggle(p, type)),
    [],
  );
  const reset = useCallback(() => {
    setHidden(new Set());
    setHighlighted(new Set());
  }, []);

  return { hidden, highlighted, toggleHidden, toggleHighlighted, reset };
}
