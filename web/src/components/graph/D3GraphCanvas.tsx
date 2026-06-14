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

interface D3GraphCanvasProps {
  nodes: LocalGraphNode[];
  edges: LocalGraphEdge[];
  rootNodeId?: string;
  highlightNodeId?: string;
  onNodeClick: (node: LocalGraphNode) => void;
  width?: number;
  height: number;
  ariaLabel?: string;
}

type SimNode = LocalGraphNode & d3.SimulationNodeDatum;

type SimEdge = Omit<LocalGraphEdge, "source" | "target"> &
  d3.SimulationLinkDatum<SimNode>;

/** Read a CSS custom property from :root, falling back to a default. */
function getCssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Build a color function that reads from tokens at render time. */
function makeNodeColorFn(): (type: string, subjectId?: string) => string {
  const noteColor = getCssVar(GRAPH_CSS_VARS.nodeNote, "#1d6d4f");
  const entityColor = getCssVar(GRAPH_CSS_VARS.nodeEntity, "#4568a6");
  const otherColor = getCssVar(GRAPH_CSS_VARS.nodeOther, "#6c6f75");
  const subjectScale = d3.scaleOrdinal(d3.schemeTableau10);

  return (type: string, subjectId?: string) => {
    if (type === "note" && subjectId) return subjectScale(subjectId);
    if (type === "note") return noteColor;
    if (type === "entity") return entityColor;
    return otherColor;
  };
}

/** Compute a quadratic bezier control point offset perpendicular to source→target. */
function curvedPath(
  sx: number, sy: number, tx: number, ty: number, offset: number,
): string {
  const mx = (sx + tx) / 2;
  const my = (sy + ty) / 2;
  const dx = tx - sx;
  const dy = ty - sy;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const cx = mx - (dy / len) * offset;
  const cy = my + (dx / len) * offset;
  return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`;
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
}: D3GraphCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const simNodesRef = useRef<SimNode[]>([]);

  useEffect(() => {
    if (!svgRef.current) return;

    const rect = svgRef.current.getBoundingClientRect();
    const width = widthProp ?? (rect.width > 0 ? rect.width : 800);

    // Cap node count — retain highest-connected nodes
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

    const simNodes: SimNode[] = renderNodes.map((n) => ({ ...n }));
    const simEdges: SimEdge[] = renderEdges.map((e) => ({ ...e }));
    simNodesRef.current = simNodes;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const g = svg.append("g").attr("class", "graph-root");
    const getNodeColor = makeNodeColorFn();
    const edgeColor = getCssVar(GRAPH_CSS_VARS.edge, "#8ba296");
    const highlightColor = getCssVar(GRAPH_CSS_VARS.nodeHighlight, "#e07b1a");
    const edgeDimColor = getCssVar(GRAPH_CSS_VARS.edgeDim, "rgba(139,162,150,0.15)");
    const nodeDimOpacity = parseFloat(getCssVar(GRAPH_CSS_VARS.nodeDimOpacity, "0.2")) || 0.2;
    const strokeDefault = getCssVar(GRAPH_CSS_VARS.nodeStrokeDefault, "#ffffff");
    const strokeRoot = getCssVar(GRAPH_CSS_VARS.nodeStrokeRoot, "#0f4e39");
    const strokeHighlight = getCssVar(GRAPH_CSS_VARS.nodeStrokeHighlight, "#b85e10");
    const labelDefault = getCssVar(GRAPH_CSS_VARS.labelDefault, "#6c6f75");
    const labelHighlight = getCssVar(GRAPH_CSS_VARS.labelHighlight, "#7a3d0a");

    // Build adjacency map for hover interaction
    const adjacency = new Map<string, Set<string>>();
    for (const e of simEdges) {
      const sId = typeof e.source === "string" ? e.source : (e.source as SimNode).id;
      const tId = typeof e.target === "string" ? e.target : (e.target as SimNode).id;
      if (!adjacency.has(sId)) adjacency.set(sId, new Set());
      if (!adjacency.has(tId)) adjacency.set(tId, new Set());
      adjacency.get(sId)!.add(tId);
      adjacency.get(tId)!.add(sId);
    }

    // ── Edges (curved paths) ──
    const linkSelection = g
      .selectAll<SVGPathElement, SimEdge>("path.graph-edge")
      .data(simEdges)
      .enter()
      .append("path")
      .attr("class", "graph-edge")
      .attr("fill", "none")
      .attr("stroke", edgeColor)
      .attr("stroke-width", 1.5)
      .attr("opacity", 0);

    // ── Nodes ──
    const nodeSelection = g
      .selectAll<SVGGElement, SimNode>("g.node")
      .data(simNodes)
      .enter()
      .append("g")
      .attr("class", "node")
      .style("cursor", "pointer")
      .attr("opacity", 0);

    nodeSelection.each(function (d) {
      const isRoot = rootNodeId === d.id;
      const isHighlight = highlightNodeId === d.id;
      const radius = isHighlight
        ? GRAPH_SIZES.highlightRadius
        : isRoot
          ? GRAPH_SIZES.rootRadius
          : GRAPH_SIZES.nodeRadius;
      const subjectId = d.metadata?.subject_id as string | undefined;
      const fillColor = isHighlight ? highlightColor : getNodeColor(d.type, subjectId);

      d3.select(this)
        .append("circle")
        .attr("r", radius)
        .attr("fill", fillColor)
        .attr("stroke", isHighlight ? strokeHighlight : isRoot ? strokeRoot : strokeDefault)
        .attr("stroke-width", isHighlight ? 3 : isRoot ? 2 : 1);

      d3.select(this)
        .append("text")
        .attr("dy", "0.35em")
        .attr("x", radius + 4)
        .attr("font-size", isHighlight ? "11" : "10")
        .attr("font-weight", isHighlight ? "600" : "normal")
        .attr("fill", isHighlight ? labelHighlight : labelDefault)
        .attr("pointer-events", "none")
        .text(
          d.label.length > GRAPH_SIZES.labelMaxChars
            ? `${d.label.slice(0, GRAPH_SIZES.labelMaxChars - 1)}…`
            : d.label,
        );
    });

    // ── Hover interaction ──
    nodeSelection
      .on("mouseenter", (_event, d) => {
        const neighbors = adjacency.get(d.id) ?? new Set<string>();
        nodeSelection.transition().duration(150).attr("opacity", (n) =>
          n.id === d.id || neighbors.has(n.id) ? 1 : nodeDimOpacity,
        );
        linkSelection.transition().duration(150)
          .attr("stroke", (e) => {
            const sId = (e.source as SimNode).id;
            const tId = (e.target as SimNode).id;
            return sId === d.id || tId === d.id ? edgeColor : edgeDimColor;
          })
          .attr("opacity", (e) => {
            const sId = (e.source as SimNode).id;
            const tId = (e.target as SimNode).id;
            return sId === d.id || tId === d.id ? 0.9 : 0.15;
          });
      })
      .on("mouseleave", () => {
        nodeSelection.transition().duration(150).attr("opacity", 1);
        linkSelection.transition().duration(150)
          .attr("stroke", edgeColor)
          .attr("opacity", 0.7);
      });

    nodeSelection.on("click", (_event, d) => {
      const original = nodes.find((n) => n.id === d.id);
      if (original) onNodeClick(original);
    });

    // ── Entrance animations ──
    linkSelection
      .transition()
      .duration(GRAPH_ANIMATION.entranceDuration)
      .delay((_d, i) => i * 2)
      .attr("opacity", 0.7);

    nodeSelection
      .transition()
      .duration(GRAPH_ANIMATION.entranceDuration)
      .delay((_d, i) => i * 5)
      .attr("opacity", 1);

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
      .force("collide", d3.forceCollide<SimNode>(GRAPH_FORCES.collideRadius));

    simulation.on("tick", () => {
      linkSelection.attr("d", (d) => {
        const s = d.source as SimNode;
        const t = d.target as SimNode;
        return curvedPath(
          s.x ?? 0, s.y ?? 0, t.x ?? 0, t.y ?? 0,
          GRAPH_SIZES.curveOffset,
        );
      });
      nodeSelection.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
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

    nodeSelection.call(drag);

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });

    svg.call(zoom);
    zoomRef.current = zoom;

    // Zoom to fit after simulation settles
    const fitAll = () => {
      if (simNodes.length === 0) return;
      const r = svgRef.current?.getBoundingClientRect();
      const w = r && r.width > 0 ? r.width : width;
      const h = r && r.height > 0 ? r.height : height;

      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const n of simNodes) {
        const x = n.x ?? 0;
        const y = n.y ?? 0;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
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
    };
  }, [nodes, edges, rootNodeId, highlightNodeId, onNodeClick, widthProp, height]);

  // Pan to highlighted node
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
