/** Graph rendering constants — single source of truth for forces, sizes, and animation timing. */

export const GRAPH_FORCES = {
  linkDistance: 90,
  chargeStrength: -200,
  collideRadius: 22,
  /**
   * Weak pull toward the canvas centre on both axes. Without it, disconnected
   * components fly apart under charge repulsion (nothing links them back),
   * which inflates the bounding box so fit-to-view shrinks everything into the
   * corners. A gentle centering force keeps the graph compact and framed.
   */
  centeringStrength: 0.06,
} as const;

export const GRAPH_SIZES = {
  nodeRadius: 11,
  rootRadius: 14,
  highlightRadius: 16,
  maxRenderNodes: 300,
  fitPadding: 56,
  labelMaxChars: 24,
  curveOffset: 15,
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
  nodeNote: "--graph-node-note",
  nodeEntity: "--graph-node-entity",
  nodeOther: "--graph-node-other",
  edge: "--graph-edge",
  nodeHighlight: "--graph-node-highlight",
  edgeDim: "--graph-edge-dim",
  nodeDimOpacity: "--graph-node-dim-opacity",
  nodeStrokeDefault: "--graph-node-stroke-default",
  nodeStrokeRoot: "--graph-node-stroke-root",
  nodeStrokeHighlight: "--graph-node-stroke-highlight",
  labelDefault: "--graph-label-default",
  labelHighlight: "--graph-label-highlight",
} as const;
