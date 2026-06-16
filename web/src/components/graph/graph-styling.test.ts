import { describe, expect, it } from "vitest";

import {
  EDGE_GROUPS,
  KNOWN_EDGE_TYPES,
  computeHierarchy,
  getEdgeStyle,
  nodeWidgetMetrics,
  wrapLabel,
} from "./graph-styling";
import type { LocalGraphEdge, LocalGraphNode } from "../../../../shared/contracts/ts/v1/graph";

function node(id: string, type = "entity", label = id): LocalGraphNode {
  return { id, type, label, confidence: null, source_note_id: null, metadata: {} };
}
function edge(source: string, target: string, type: string): LocalGraphEdge {
  return { id: `${source}-${type}-${target}`, source, target, type, confidence: null, source_note_id: null };
}

describe("getEdgeStyle", () => {
  it("maps known hierarchy types to a directed, arrowed style", () => {
    const isA = getEdgeStyle("IS_A");
    expect(isA.group).toBe("hierarchy");
    expect(isA.directed).toBe(true);
    expect(isA.label).toBe("is a");

    const subtopic = getEdgeStyle("SUBTOPIC_OF");
    expect(subtopic.group).toBe("hierarchy");
    expect(subtopic.directed).toBe(true);
  });

  it("maps SYNONYM_OF to an undirected equivalence style with a dash pattern", () => {
    const syn = getEdgeStyle("SYNONYM_OF");
    expect(syn.group).toBe("equivalence");
    expect(syn.directed).toBe(false);
    expect(syn.dash.length).toBeGreaterThan(0);
  });

  it("distinguishes association types by dash form", () => {
    const sibling = getEdgeStyle("SIBLING_OF");
    const mentioned = getEdgeStyle("MENTIONED_TOGETHER");
    // Different forms so they are visually distinguishable.
    expect(sibling.dash).not.toBe(mentioned.dash);
  });

  it("falls back to a neutral association style for unknown types", () => {
    const unknown = getEdgeStyle("SOMETHING_NEW");
    expect(unknown.group).toBe("association");
    expect(unknown.label).toBe("something new");
  });
});

describe("EDGE_GROUPS", () => {
  it("covers every known edge type exactly once across groups", () => {
    const grouped = EDGE_GROUPS.flatMap((g) => g.types);
    expect(new Set(grouped).size).toBe(grouped.length); // no duplicates
    expect(new Set(grouped)).toEqual(new Set(KNOWN_EDGE_TYPES));
  });

  it("gives every group a human label", () => {
    for (const g of EDGE_GROUPS) {
      expect(g.label.length).toBeGreaterThan(0);
      expect(g.types.length).toBeGreaterThan(0);
    }
  });
});

describe("computeHierarchy", () => {
  it("assigns increasing depth from parent down a chain and flags parents", () => {
    // deep network -> neural network -> network  (child IS_A parent)
    const nodes = [node("deep"), node("neural"), node("network")];
    const edges = [edge("deep", "neural", "IS_A"), edge("neural", "network", "IS_A")];
    const h = computeHierarchy(nodes, edges);

    expect(h.get("network")!.depth).toBe(0);
    expect(h.get("neural")!.depth).toBe(1);
    expect(h.get("deep")!.depth).toBe(2);

    expect(h.get("network")!.isParent).toBe(true);
    expect(h.get("neural")!.isParent).toBe(true); // parent of "deep"
    expect(h.get("deep")!.isParent).toBe(false); // leaf
  });

  it("ignores non-hierarchy edges", () => {
    const nodes = [node("a"), node("b")];
    const edges = [edge("a", "b", "MENTIONED_TOGETHER")];
    const h = computeHierarchy(nodes, edges);
    expect(h.get("a")!.isParent).toBe(false);
    expect(h.get("b")!.isParent).toBe(false);
  });

  it("is cycle-safe (does not loop forever)", () => {
    const nodes = [node("a"), node("b")];
    const edges = [edge("a", "b", "IS_A"), edge("b", "a", "IS_A")];
    const h = computeHierarchy(nodes, edges);
    expect(h.size).toBe(2);
  });

  it("treats isolated nodes as depth 0 leaves", () => {
    const nodes = [node("lonely")];
    const h = computeHierarchy(nodes, []);
    expect(h.get("lonely")).toEqual({ depth: 0, isParent: false });
  });
});

describe("wrapLabel", () => {
  it("returns a single line for a short label", () => {
    expect(wrapLabel("network", 12, 3)).toEqual(["network"]);
  });

  it("wraps multi-word labels onto multiple lines", () => {
    const lines = wrapLabel("deep neural network", 12, 3);
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.join(" ")).toBe("deep neural network");
  });

  it("truncates with an ellipsis past maxLines", () => {
    const lines = wrapLabel("one two three four five six seven", 5, 2);
    expect(lines.length).toBe(2);
    expect(lines[lines.length - 1]).toMatch(/…$/);
  });

  it("hard-breaks a single word longer than the line width", () => {
    const lines = wrapLabel("supercalifragilistic", 6, 3);
    expect(lines[0].length).toBeLessThanOrEqual(7); // width + ellipsis tolerance
  });

  it("handles empty strings", () => {
    expect(wrapLabel("", 12, 3)).toEqual([""]);
  });
});

describe("nodeWidgetMetrics", () => {
  it("makes hierarchy parents larger than leaves", () => {
    const parent = nodeWidgetMetrics(node("p"), { depth: 0, isParent: true });
    const leaf = nodeWidgetMetrics(node("c"), { depth: 2, isParent: false });
    expect(parent.width).toBeGreaterThan(leaf.width);
    expect(parent.fontSize).toBeGreaterThanOrEqual(leaf.fontSize);
  });

  it("sizes note widgets differently from concept widgets", () => {
    const noteW = nodeWidgetMetrics(node("n", "note"), { depth: 0, isParent: false });
    const conceptW = nodeWidgetMetrics(node("c", "entity"), { depth: 0, isParent: false });
    expect(noteW.width).not.toBe(conceptW.width);
  });
});
