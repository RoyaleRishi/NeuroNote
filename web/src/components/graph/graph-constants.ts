/** Graph rendering constants — single source of truth for forces, sizes, and animation timing. */

export const GRAPH_FORCES = {
  linkDistance: 150,
  chargeStrength: -650,
  /**
   * Weak pull toward the canvas centre on both axes. Without it, disconnected
   * components fly apart under charge repulsion (nothing links them back),
   * which inflates the bounding box so fit-to-view shrinks everything into the
   * corners. A gentle centering force keeps the graph compact and framed.
   */
  centeringStrength: 0.06,
} as const;

export const GRAPH_SIZES = {
  maxRenderNodes: 300,
  fitPadding: 56,
  curveOffset: 18,
  /** Upper bound on widget width; longer single words wrap past this. */
  widgetMaxWidth: 220,
  /** Arrowhead marker box (userSpaceOnUse) for directed edges. */
  arrowSize: 9,
  /** Font size for on-edge relationship name labels. */
  edgeLabelFontSize: 9,
  /** Extra collision padding around a widget's half-diagonal. */
  collidePadding: 10,
} as const;

export const GRAPH_ANIMATION = {
  fitDuration: 300,
  panDuration: 400,
  entranceDuration: 400,
} as const;

export const GRAPH_THRESHOLDS = {
  /** Node count above which alphaDecay is increased to settle the simulation faster. */
  largeGraphNodeCount: 150,
  fastAlphaDecay: 0.05,
  defaultAlphaDecay: 0.0228,
} as const;

/** CSS custom property names from tokens.css — read via getComputedStyle at render time. */
export const GRAPH_CSS_VARS = {
  // Typed border colours (also used as the note/entity accent).
  nodeNote: "--graph-node-note",
  nodeEntity: "--graph-node-entity",
  nodeOther: "--graph-node-other",
  // Soft widget fills + their "strong" (parent) variants.
  nodeNoteFill: "--graph-node-note-fill",
  nodeNoteFillStrong: "--graph-node-note-fill-strong",
  nodeNoteStrong: "--graph-node-note-strong",
  nodeEntityFill: "--graph-node-entity-fill",
  nodeEntityFillStrong: "--graph-node-entity-fill-strong",
  nodeEntityStrong: "--graph-node-entity-strong",
  nodeOtherFill: "--graph-node-other-fill",
  nodeOtherFillStrong: "--graph-node-other-fill-strong",
  nodeOtherStrong: "--graph-node-other-strong",
  // Highlight (search / hover focus).
  nodeHighlight: "--graph-node-highlight",
  nodeHighlightFill: "--graph-node-highlight-fill",
  nodeStrokeHighlight: "--graph-node-stroke-highlight",
  // Widget text + dimming.
  widgetText: "--graph-widget-text",
  nodeDimOpacity: "--graph-node-dim-opacity",
  // Edge colours by relationship family.
  edge: "--graph-edge",
  edgeHierarchy: "--graph-edge-hierarchy",
  edgeEquivalence: "--graph-edge-equivalence",
  edgeLink: "--graph-edge-link",
  edgeLabel: "--graph-edge-label",
  edgeDim: "--graph-edge-dim",
} as const;
