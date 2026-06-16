"use client";

import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { LocalGraphNode, LocalGraphEdge } from "../../../../shared/contracts/ts/v1/graph";
import {
  GRAPH_FORCES,
  GRAPH_SIZES,
  GRAPH_ANIMATION,
  GRAPH_THRESHOLDS,
  GRAPH_CSS_VARS,
} from "./graph-constants";
import {
  computeHierarchy,
  getEdgeStyle,
  nodeWidgetMetrics,
  wrapLabel,
  type EdgeGroupId,
  type HierarchyInfo,
} from "./graph-styling";

interface D3GraphCanvasProps {
  nodes: LocalGraphNode[];
  edges: LocalGraphEdge[];
  rootNodeId?: string;
  highlightNodeId?: string;
  onNodeClick: (node: LocalGraphNode) => void;
  width?: number;
  height: number;
  ariaLabel?: string;
  /** Edge types to hide entirely (driven by the legend). */
  hiddenEdgeTypes?: Set<string>;
  /** Edge types to emphasise; when non-empty, others dim (driven by the legend). */
  highlightedEdgeTypes?: Set<string>;
}

type SimNode = LocalGraphNode &
  d3.SimulationNodeDatum & { w: number; h: number; r: number };

type SimEdge = Omit<LocalGraphEdge, "source" | "target"> &
  d3.SimulationLinkDatum<SimNode>;

const BASE_EDGE_OPACITY = 0.72;
const EMPTY_SET: Set<string> = new Set();

/** Read a CSS custom property from :root, falling back to a default. */
function getCssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/**
 * Quadratic-bezier path between two points, plus the curve's midpoint (t=0.5)
 * for placing an edge label.
 */
function curvedPath(
  sx: number, sy: number, tx: number, ty: number, offset: number,
): { d: string; lx: number; ly: number } {
  const mx = (sx + tx) / 2;
  const my = (sy + ty) / 2;
  const dx = tx - sx;
  const dy = ty - sy;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const cx = mx - (dy / len) * offset;
  const cy = my + (dx / len) * offset;
  const lx = 0.25 * sx + 0.5 * cx + 0.25 * tx;
  const ly = 0.25 * sy + 0.5 * cy + 0.25 * ty;
  return { d: `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`, lx, ly };
}

/** Pull an endpoint in toward the line by `gap` so an arrowhead clears the widget. */
function trim(px: number, py: number, qx: number, qy: number, gap: number): [number, number] {
  const dx = qx - px;
  const dy = qy - py;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  return [px + (dx / len) * gap, py + (dy / len) * gap];
}

export function D3GraphCanvas({
  nodes,
  edges,
  rootNodeId,
  highlightNodeId,
  onNodeClick,
  width: widthProp,
  height,
  ariaLabel,
  hiddenEdgeTypes,
  highlightedEdgeTypes,
}: D3GraphCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const simNodesRef = useRef<SimNode[]>([]);
  // Latest control sets + a re-styling function, so legend toggles restyle the
  // existing canvas without rebuilding the force layout (positions stay put).
  const hiddenRef = useRef<Set<string>>(hiddenEdgeTypes ?? EMPTY_SET);
  const highlightedRef = useRef<Set<string>>(highlightedEdgeTypes ?? EMPTY_SET);
  const applyControlsRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!svgRef.current) return;

    const rect = svgRef.current.getBoundingClientRect();
    const width = widthProp ?? (rect.width > 0 ? rect.width : 800);

    // Cap node count — retain highest-connected nodes.
    let renderNodes = nodes;
    let renderEdges = edges;
    if (nodes.length > GRAPH_SIZES.maxRenderNodes) {
      const edgeDegree = new Map<string, number>();
      for (const e of edges) {
        edgeDegree.set(e.source, (edgeDegree.get(e.source) ?? 0) + 1);
        edgeDegree.set(e.target, (edgeDegree.get(e.target) ?? 0) + 1);
      }
      renderNodes = [...nodes]
        .sort((a, b) => (edgeDegree.get(b.id) ?? 0) - (edgeDegree.get(a.id) ?? 0))
        .slice(0, GRAPH_SIZES.maxRenderNodes);
      const visibleIds = new Set(renderNodes.map((n) => n.id));
      renderEdges = edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target));
    }

    const hierarchy = computeHierarchy(renderNodes, renderEdges);

    // Pre-compute widget geometry + wrapped label lines per node.
    const layout = new Map<string, { w: number; h: number; lines: string[]; metrics: ReturnType<typeof nodeWidgetMetrics> }>();
    for (const n of renderNodes) {
      const info: HierarchyInfo = hierarchy.get(n.id) ?? { depth: 0, isParent: false };
      const metrics = nodeWidgetMetrics(n, info);
      // Widen the widget to fit its longest word so we never hard-break a
      // single word ("backpropagatio n"); cap so pathological tokens still wrap.
      const charW = metrics.fontSize * 0.58;
      const longestWord = n.label.split(/\s+/).reduce((m, w) => Math.max(m, w.length), 1);
      const w = Math.min(
        GRAPH_SIZES.widgetMaxWidth,
        Math.max(metrics.width, Math.ceil(longestWord * charW) + metrics.paddingX * 2),
      );
      const maxChars = Math.max(metrics.maxCharsPerLine, Math.floor((w - metrics.paddingX * 2) / charW));
      const lines = wrapLabel(n.label, maxChars, metrics.maxLines);
      const h = Math.max(metrics.minHeight, lines.length * metrics.lineHeight + metrics.paddingY * 2);
      layout.set(n.id, { w, h, lines, metrics });
    }

    const simNodes: SimNode[] = renderNodes.map((n) => {
      const l = layout.get(n.id)!;
      return { ...n, w: l.w, h: l.h, r: Math.hypot(l.w, l.h) / 2 + GRAPH_SIZES.collidePadding };
    });
    const simEdges: SimEdge[] = renderEdges.map((e) => ({ ...e }));
    simNodesRef.current = simNodes;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const g = svg.append("g").attr("class", "graph-root");

    // ── Resolve palette from tokens at render time ──
    const edgeColors: Record<EdgeGroupId, string> = {
      hierarchy: getCssVar(GRAPH_CSS_VARS.edgeHierarchy, "#335a30"),
      equivalence: getCssVar(GRAPH_CSS_VARS.edgeEquivalence, "#9a6b34"),
      association: getCssVar(GRAPH_CSS_VARS.edge, "#b8a585"),
      notes: getCssVar(GRAPH_CSS_VARS.edgeLink, "#5b6f8a"),
    };
    const edgeLabelColor = getCssVar(GRAPH_CSS_VARS.edgeLabel, "#6f6450");
    const widgetText = getCssVar(GRAPH_CSS_VARS.widgetText, "#3a3122");
    const highlightFill = getCssVar(GRAPH_CSS_VARS.nodeHighlightFill, "#fbe6c9");
    const highlightStroke = getCssVar(GRAPH_CSS_VARS.nodeStrokeHighlight, "#b85e10");
    const nodeDimOpacity = parseFloat(getCssVar(GRAPH_CSS_VARS.nodeDimOpacity, "0.2")) || 0.2;

    const typeFill = (n: SimNode, info: HierarchyInfo): string => {
      const strong = info.isParent;
      if (n.type === "note") return getCssVar(strong ? GRAPH_CSS_VARS.nodeNoteFillStrong : GRAPH_CSS_VARS.nodeNoteFill, "#e9efe2");
      if (n.type === "entity") return getCssVar(strong ? GRAPH_CSS_VARS.nodeEntityFillStrong : GRAPH_CSS_VARS.nodeEntityFill, "#f1e6d4");
      return getCssVar(strong ? GRAPH_CSS_VARS.nodeOtherFillStrong : GRAPH_CSS_VARS.nodeOtherFill, "#ece7dd");
    };
    const typeStroke = (n: SimNode, info: HierarchyInfo): string => {
      const strong = info.isParent;
      if (n.type === "note") return getCssVar(strong ? GRAPH_CSS_VARS.nodeNoteStrong : GRAPH_CSS_VARS.nodeNote, "#3f6b3a");
      if (n.type === "entity") return getCssVar(strong ? GRAPH_CSS_VARS.nodeEntityStrong : GRAPH_CSS_VARS.nodeEntity, "#9a6b34");
      return getCssVar(strong ? GRAPH_CSS_VARS.nodeOtherStrong : GRAPH_CSS_VARS.nodeOther, "#7a6f5a");
    };
    const groupColor = (type: string): string => edgeColors[getEdgeStyle(type).group];

    // ── Arrowhead markers, one per edge-group colour ──
    const defs = g.append("defs");
    (Object.keys(edgeColors) as EdgeGroupId[]).forEach((group) => {
      defs
        .append("marker")
        .attr("id", `arrow-${group}`)
        .attr("markerWidth", GRAPH_SIZES.arrowSize)
        .attr("markerHeight", GRAPH_SIZES.arrowSize)
        .attr("refX", GRAPH_SIZES.arrowSize - 1)
        .attr("refY", GRAPH_SIZES.arrowSize / 2)
        .attr("orient", "auto")
        .attr("markerUnits", "userSpaceOnUse")
        .append("path")
        .attr(
          "d",
          `M0,0 L${GRAPH_SIZES.arrowSize},${GRAPH_SIZES.arrowSize / 2} L0,${GRAPH_SIZES.arrowSize} Z`,
        )
        .attr("fill", edgeColors[group]);
    });

    // Adjacency for hover focus.
    const adjacency = new Map<string, Set<string>>();
    for (const e of simEdges) {
      const sId = typeof e.source === "string" ? e.source : (e.source as SimNode).id;
      const tId = typeof e.target === "string" ? e.target : (e.target as SimNode).id;
      if (!adjacency.has(sId)) adjacency.set(sId, new Set());
      if (!adjacency.has(tId)) adjacency.set(tId, new Set());
      adjacency.get(sId)!.add(tId);
      adjacency.get(tId)!.add(sId);
    }

    // ── Edges (typed curved paths) ──
    const linkSel = g
      .selectAll<SVGPathElement, SimEdge>("path.graph-edge")
      .data(simEdges)
      .enter()
      .append("path")
      .attr("class", "graph-edge")
      .attr("fill", "none")
      .attr("stroke", (e) => groupColor(e.type))
      .attr("stroke-width", (e) => getEdgeStyle(e.type).width)
      .attr("stroke-dasharray", (e) => getEdgeStyle(e.type).dash || null)
      .attr("stroke-linecap", "round")
      .attr("marker-end", (e) =>
        getEdgeStyle(e.type).directed ? `url(#arrow-${getEdgeStyle(e.type).group})` : null,
      )
      .attr("opacity", BASE_EDGE_OPACITY);

    // ── Edge name labels (shown when a type is highlighted) ──
    const edgeLabelSel = g
      .selectAll<SVGTextElement, SimEdge>("text.graph-edge-label")
      .data(simEdges)
      .enter()
      .append("text")
      .attr("class", "graph-edge-label")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "central")
      .attr("font-size", GRAPH_SIZES.edgeLabelFontSize)
      .attr("fill", edgeLabelColor)
      .attr("paint-order", "stroke")
      .attr("stroke", "var(--panel-bg)")
      .attr("stroke-width", 3)
      .attr("pointer-events", "none")
      .style("display", "none")
      .text((e) => getEdgeStyle(e.type).label);

    // ── Nodes as widgets ──
    const nodeSel = g
      .selectAll<SVGGElement, SimNode>("g.node")
      .data(simNodes)
      .enter()
      .append("g")
      .attr("class", "node")
      .style("cursor", "pointer")
      .attr("opacity", 0);

    nodeSel.each(function (d) {
      const l = layout.get(d.id)!;
      const info: HierarchyInfo = hierarchy.get(d.id) ?? { depth: 0, isParent: false };
      const isHighlight = highlightNodeId === d.id;
      const sel = d3.select(this);

      sel
        .append("rect")
        .attr("x", -l.w / 2)
        .attr("y", -l.h / 2)
        .attr("width", l.w)
        .attr("height", l.h)
        .attr("rx", Math.min(l.metrics.radius, l.h / 2))
        .attr("fill", isHighlight ? highlightFill : typeFill(d, info))
        .attr("stroke", isHighlight ? highlightStroke : typeStroke(d, info))
        .attr("stroke-width", isHighlight ? 2.5 : info.isParent ? 2.4 : 1.4)
        .attr("filter", "drop-shadow(0 1px 1.5px rgba(58,49,34,0.18))");

      const text = sel
        .append("text")
        .attr("text-anchor", "middle")
        .attr("fill", widgetText)
        .attr("font-size", l.metrics.fontSize)
        .attr("font-weight", info.isParent || isHighlight ? 600 : 500)
        .attr("pointer-events", "none");

      const startY = -((l.lines.length - 1) * l.metrics.lineHeight) / 2;
      l.lines.forEach((line, i) => {
        text
          .append("tspan")
          .attr("x", 0)
          .attr("y", startY + i * l.metrics.lineHeight)
          .attr("dominant-baseline", "central")
          .text(line);
      });
    });

    // ── Re-styling baseline driven by the legend control sets ──
    const applyControls = () => {
      const hidden = hiddenRef.current;
      const highlighted = highlightedRef.current;
      const anyHi = highlighted.size > 0;

      const hiNodes = new Set<string>();
      if (anyHi) {
        for (const e of simEdges) {
          if (!highlighted.has(e.type)) continue;
          hiNodes.add((e.source as SimNode).id);
          hiNodes.add((e.target as SimNode).id);
        }
      }

      linkSel
        .style("display", (e) => (hidden.has(e.type) ? "none" : null))
        .attr("stroke", (e) => groupColor(e.type))
        .attr("stroke-width", (e) => {
          const base = getEdgeStyle(e.type).width;
          return anyHi && highlighted.has(e.type) ? base + 1.2 : base;
        })
        .attr("opacity", (e) => {
          if (hidden.has(e.type)) return 0;
          if (!anyHi) return BASE_EDGE_OPACITY;
          return highlighted.has(e.type) ? 1 : 0.1;
        });

      edgeLabelSel.style("display", (e) =>
        !hidden.has(e.type) && anyHi && highlighted.has(e.type) ? null : "none",
      );

      nodeSel.attr("opacity", (n) => (anyHi && !hiNodes.has(n.id) ? nodeDimOpacity : 1));
    };
    applyControlsRef.current = applyControls;

    // ── Hover focus (dims non-neighbours; restores to control baseline on leave) ──
    nodeSel
      .on("mouseenter", (_event, d) => {
        const neighbors = adjacency.get(d.id) ?? new Set<string>();
        nodeSel
          .transition()
          .duration(150)
          .attr("opacity", (n) => (n.id === d.id || neighbors.has(n.id) ? 1 : nodeDimOpacity));
        linkSel
          .transition()
          .duration(150)
          .attr("opacity", (e) => {
            if (hiddenRef.current.has(e.type)) return 0;
            const sId = (e.source as SimNode).id;
            const tId = (e.target as SimNode).id;
            return sId === d.id || tId === d.id ? 0.95 : 0.08;
          });
      })
      .on("mouseleave", () => {
        nodeSel.interrupt();
        linkSel.interrupt();
        applyControls();
      });

    nodeSel.on("click", (_event, d) => {
      const original = nodes.find((n) => n.id === d.id);
      if (original) onNodeClick(original);
    });

    // ── Entrance ──
    nodeSel
      .transition()
      .duration(GRAPH_ANIMATION.entranceDuration)
      .delay((_d, i) => i * 5)
      .attr("opacity", 1);

    applyControls();

    // ── Force simulation ──
    const alphaDecay =
      simNodes.length > GRAPH_THRESHOLDS.largeGraphNodeCount
        ? GRAPH_THRESHOLDS.fastAlphaDecay
        : GRAPH_THRESHOLDS.defaultAlphaDecay;

    const simulation = d3
      .forceSimulation<SimNode>(simNodes)
      .alphaDecay(alphaDecay)
      .force(
        "link",
        d3.forceLink<SimNode, SimEdge>(simEdges).id((d) => d.id).distance(GRAPH_FORCES.linkDistance),
      )
      .force("charge", d3.forceManyBody<SimNode>().strength(GRAPH_FORCES.chargeStrength))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("x", d3.forceX<SimNode>(width / 2).strength(GRAPH_FORCES.centeringStrength))
      .force("y", d3.forceY<SimNode>(height / 2).strength(GRAPH_FORCES.centeringStrength))
      .force("collide", d3.forceCollide<SimNode>((d) => d.r));

    simulation.on("tick", () => {
      linkSel.attr("d", (d) => {
        const s = d.source as SimNode;
        const t = d.target as SimNode;
        const [sx, sy] = trim(s.x ?? 0, s.y ?? 0, t.x ?? 0, t.y ?? 0, s.r * 0.6);
        const [tx, ty] = trim(t.x ?? 0, t.y ?? 0, s.x ?? 0, s.y ?? 0, t.r * 0.6);
        return curvedPath(sx, sy, tx, ty, GRAPH_SIZES.curveOffset).d;
      });
      edgeLabelSel.attr("transform", (d) => {
        const s = d.source as SimNode;
        const t = d.target as SimNode;
        const { lx, ly } = curvedPath(s.x ?? 0, s.y ?? 0, t.x ?? 0, t.y ?? 0, GRAPH_SIZES.curveOffset);
        return `translate(${lx},${ly})`;
      });
      nodeSel.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    const drag = d3
      .drag<SVGGElement, SimNode>()
      .on("start", (_event, d) => {
        simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (_event, d) => {
        simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeSel.call(drag);

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });

    svg.call(zoom);
    zoomRef.current = zoom;

    const fitAll = () => {
      if (simNodes.length === 0) return;
      const r = svgRef.current?.getBoundingClientRect();
      const w = r && r.width > 0 ? r.width : width;
      const h = r && r.height > 0 ? r.height : height;

      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const n of simNodes) {
        const x = n.x ?? 0;
        const y = n.y ?? 0;
        if (x - n.w / 2 < minX) minX = x - n.w / 2;
        if (x + n.w / 2 > maxX) maxX = x + n.w / 2;
        if (y - n.h / 2 < minY) minY = y - n.h / 2;
        if (y + n.h / 2 > maxY) maxY = y + n.h / 2;
      }
      const pad = GRAPH_SIZES.fitPadding;
      const boxW = maxX - minX + pad * 2;
      const boxH = maxY - minY + pad * 2;
      const scale = Math.min(w / boxW, h / boxH, 1.5);
      const tx = w / 2 - scale * ((minX + maxX) / 2);
      const ty = h / 2 - scale * ((minY + maxY) / 2);
      svg
        .transition()
        .duration(GRAPH_ANIMATION.fitDuration)
        .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    };

    simulation.on("end", fitAll);

    return () => {
      simulation.stop();
      svg.on(".zoom", null);
      applyControlsRef.current = null;
    };
  }, [nodes, edges, rootNodeId, highlightNodeId, onNodeClick, widthProp, height]);

  // Apply legend control changes without rebuilding the layout.
  useEffect(() => {
    hiddenRef.current = hiddenEdgeTypes ?? EMPTY_SET;
    highlightedRef.current = highlightedEdgeTypes ?? EMPTY_SET;
    applyControlsRef.current?.();
  }, [hiddenEdgeTypes, highlightedEdgeTypes]);

  // Pan to highlighted node.
  useEffect(() => {
    if (!highlightNodeId || !svgRef.current || !zoomRef.current) return;
    const node = simNodesRef.current.find((n) => n.id === highlightNodeId);
    if (!node || node.x == null || node.y == null) return;

    const r = svgRef.current.getBoundingClientRect();
    const w = r.width > 0 ? r.width : 800;
    const h = r.height > 0 ? r.height : 600;
    const scale = 2;
    const tx = w / 2 - scale * node.x;
    const ty = h / 2 - scale * node.y;
    d3.select(svgRef.current)
      .transition()
      .duration(GRAPH_ANIMATION.panDuration)
      .call(zoomRef.current.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }, [highlightNodeId]);

  return (
    <svg
      ref={svgRef}
      width={widthProp ?? "100%"}
      height={height}
      aria-label={ariaLabel}
      style={{ cursor: "grab", display: "block", background: "transparent" }}
    />
  );
}
