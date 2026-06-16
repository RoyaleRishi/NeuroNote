/**
 * Pure, framework-free styling + hierarchy logic for the knowledge graph.
 *
 * D3 + jsdom cannot lay out SVG, so every *decision* (edge form, node sizing,
 * hierarchy depth, label wrapping) lives here as unit-tested pure functions.
 * `D3GraphCanvas` stays a thin renderer that consumes these — mirroring how
 * `graph-constants.ts` already isolates the magic numbers.
 */

import type { LocalGraphEdge, LocalGraphNode } from "../../../../shared/contracts/ts/v1/graph";

/** Visual family an edge belongs to — drives both colour and legend grouping. */
export type EdgeGroupId = "hierarchy" | "equivalence" | "association" | "notes";

export interface EdgeStyle {
  /** Human, lower-case name shown in the legend and on edge labels ("is a"). */
  label: string;
  group: EdgeGroupId;
  /** Base stroke width in px — distinguishes weight (thick vs thin). */
  width: number;
  /** SVG `stroke-dasharray`; "" = solid. Distinguishes form (dotted/dashed). */
  dash: string;
  /** Whether to draw an arrowhead at the target (directional relationships). */
  directed: boolean;
}

/**
 * The complete set of edge `type` strings emitted by the backend graph services
 * (`local_graph_service.py` / `global_graph_service.py` / `graph_sync_service.py`).
 * Each gets a distinct *form* so types are separable without reading a label.
 */
const EDGE_STYLE: Record<string, EdgeStyle> = {
  // ── Hierarchy: directed child → parent, solid, heavier the more specific the relation ──
  IS_A: { label: "is a", group: "hierarchy", width: 2.6, dash: "", directed: true },
  SUBTOPIC_OF: { label: "subtopic of", group: "hierarchy", width: 2.0, dash: "", directed: true },

  // ── Equivalence: symmetric, dotted ──
  SYNONYM_OF: { label: "synonym of", group: "equivalence", width: 1.6, dash: "2 4", directed: false },

  // ── Association: each a different dash so they read apart at a glance ──
  MENTIONED_TOGETHER: { label: "mentioned together", group: "association", width: 1.2, dash: "", directed: false },
  SIBLING_OF: { label: "sibling of", group: "association", width: 1.4, dash: "6 4", directed: false },
  REFERENCES: { label: "references", group: "association", width: 1.6, dash: "10 5", directed: true },
  DEFINED_BY: { label: "defined by", group: "association", width: 1.6, dash: "8 3 2 3", directed: true },

  // ── Note linkage ──
  LINKS_TO: { label: "links to", group: "notes", width: 2.0, dash: "", directed: true },
  MENTIONS: { label: "mentions", group: "notes", width: 1.2, dash: "4 4", directed: true },
};

/** Every edge type with a defined style, in a stable order. */
export const KNOWN_EDGE_TYPES: string[] = Object.keys(EDGE_STYLE);

/** Map an `EdgeGroupId` to the CSS custom property holding its colour. */
export const EDGE_GROUP_CSS_VAR: Record<EdgeGroupId, string> = {
  hierarchy: "--graph-edge-hierarchy",
  equivalence: "--graph-edge-equivalence",
  association: "--graph-edge",
  notes: "--graph-edge-link",
};

interface EdgeGroup {
  id: EdgeGroupId;
  label: string;
  types: string[];
}

/** Legend grouping + ordering. Must cover every `KNOWN_EDGE_TYPES` entry once. */
export const EDGE_GROUPS: EdgeGroup[] = [
  { id: "hierarchy", label: "Hierarchy", types: ["IS_A", "SUBTOPIC_OF"] },
  { id: "equivalence", label: "Equivalence", types: ["SYNONYM_OF"] },
  { id: "association", label: "Association", types: ["MENTIONED_TOGETHER", "SIBLING_OF", "REFERENCES", "DEFINED_BY"] },
  { id: "notes", label: "Notes & mentions", types: ["LINKS_TO", "MENTIONS"] },
];

/** "SOMETHING_NEW" → "something new" for unknown-type fallback labels. */
function humanizeType(type: string): string {
  return type.toLowerCase().replace(/_/g, " ");
}

/** Resolve an edge `type` to its visual style, falling back for unknown types. */
export function getEdgeStyle(type: string | null | undefined): EdgeStyle {
  if (!type) {
    return { label: "", group: "association", width: 1.2, dash: "", directed: false };
  }
  return (
    EDGE_STYLE[type] ?? {
      label: humanizeType(type),
      group: "association",
      width: 1.2,
      dash: "",
      directed: false,
    }
  );
}

export interface HierarchyInfo {
  /** Distance from the topmost parent (0 = root concept). Used for depth tint. */
  depth: number;
  /** True when this node is the *parent* end of a hierarchy edge. */
  isParent: boolean;
}

/**
 * Derive a shallow hierarchy from directed hierarchy edges (`IS_A`, `SUBTOPIC_OF`),
 * treating each edge's **target** as the parent of its **source**.
 *
 * Returns per-node `{ depth, isParent }`. Cycle-safe: depth propagation is bounded
 * and only advances when it strictly increases, so cyclic data cannot loop forever.
 */
export function computeHierarchy(
  nodes: LocalGraphNode[],
  edges: LocalGraphEdge[],
): Map<string, HierarchyInfo> {
  const childrenOf = new Map<string, Set<string>>();
  const hasParent = new Set<string>();
  const isParent = new Set<string>();

  for (const e of edges) {
    const style = getEdgeStyle(e.type);
    if (style.group !== "hierarchy" || !style.directed) continue;
    const child = e.source;
    const parent = e.target;
    if (!childrenOf.has(parent)) childrenOf.set(parent, new Set());
    childrenOf.get(parent)!.add(child);
    isParent.add(parent);
    hasParent.add(child);
  }

  const depth = new Map<string, number>();
  for (const n of nodes) depth.set(n.id, 0);

  // Roots = parents that are nobody's child. BFS downward assigning increasing depth.
  const queue: Array<[string, number]> = [...isParent]
    .filter((id) => !hasParent.has(id))
    .map((id) => [id, 0]);

  const maxSteps = nodes.length * 4 + edges.length * 4 + 16;
  let steps = 0;
  while (queue.length > 0 && steps++ < maxSteps) {
    const [id, d] = queue.shift()!;
    const cur = Math.max(depth.get(id) ?? 0, d);
    depth.set(id, cur);
    for (const child of childrenOf.get(id) ?? []) {
      if ((depth.get(child) ?? 0) < cur + 1) {
        depth.set(child, cur + 1);
        queue.push([child, cur + 1]);
      }
    }
  }

  const result = new Map<string, HierarchyInfo>();
  for (const n of nodes) {
    result.set(n.id, { depth: depth.get(n.id) ?? 0, isParent: isParent.has(n.id) });
  }
  return result;
}

export interface WidgetMetrics {
  width: number;
  minHeight: number;
  fontSize: number;
  lineHeight: number;
  paddingX: number;
  paddingY: number;
  maxCharsPerLine: number;
  maxLines: number;
  radius: number;
}

/**
 * Base widget dimensions for a node. Notes render as wider "cards"; concepts as
 * narrower "pills". Hierarchy parents are scaled up so the hierarchy reads at a
 * glance even within the force layout.
 */
export function nodeWidgetMetrics(node: LocalGraphNode, hierarchy: HierarchyInfo): WidgetMetrics {
  const isNote = node.type === "note";
  const parentBoost = hierarchy.isParent ? 1.18 : 1;

  const baseWidth = isNote ? 140 : 118;
  const baseFont = 11;

  const width = Math.round(baseWidth * parentBoost);
  const fontSize = hierarchy.isParent ? baseFont + 1 : baseFont;
  const lineHeight = Math.round(fontSize * 1.25);
  const paddingX = 12;
  const paddingY = 8;
  // ~6.2px per char at our font; reserve padding on both sides.
  const maxCharsPerLine = Math.max(6, Math.floor((width - paddingX * 2) / (fontSize * 0.58)));

  return {
    width,
    minHeight: lineHeight + paddingY * 2,
    fontSize,
    lineHeight,
    paddingX,
    paddingY,
    maxCharsPerLine,
    maxLines: 3,
    radius: isNote ? 8 : 999, // card corners vs full pill
  };
}

/**
 * Greedy word-wrap into at most `maxLines` lines of `maxCharsPerLine` chars.
 * Hard-breaks words longer than a line; ellipsises overflow past `maxLines`.
 */
export function wrapLabel(text: string, maxCharsPerLine: number, maxLines: number): string[] {
  if (text.length === 0) return [""];

  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let current = "";
  const flush = () => {
    if (current) {
      lines.push(current);
      current = "";
    }
  };

  for (let word of words) {
    while (word.length > maxCharsPerLine) {
      flush();
      lines.push(word.slice(0, maxCharsPerLine));
      word = word.slice(maxCharsPerLine);
    }
    if (!current) current = word;
    else if (`${current} ${word}`.length <= maxCharsPerLine) current = `${current} ${word}`;
    else {
      flush();
      current = word;
    }
  }
  flush();

  if (lines.length === 0) return [""];
  if (lines.length <= maxLines) return lines;

  const kept = lines.slice(0, maxLines);
  let last = kept[maxLines - 1];
  if (last.length >= maxCharsPerLine) last = last.slice(0, Math.max(1, maxCharsPerLine - 1));
  kept[maxLines - 1] = `${last.replace(/\s+$/, "")}…`;
  return kept;
}
