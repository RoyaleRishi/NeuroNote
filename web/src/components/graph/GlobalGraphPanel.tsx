"use client";

import { useEffect, useRef, useState } from "react";

import { D3GraphCanvas } from "./D3GraphCanvas";
import { GraphLegend } from "./GraphLegend";
import { ConceptInsightPanel } from "./ConceptInsightPanel";
import { FilterCombobox } from "../ui/FilterCombobox";
import type { GlobalGraphResponse, LocalGraphNode } from "../../../../shared/contracts/ts/v1/graph";
import { SkeletonGraph } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { ErrorMessage } from "../ui/ErrorMessage";
import type { GlobalGraphFilters } from "../../lib/hooks/useGlobalGraph";
import { useGraphEdgeControls } from "../../lib/hooks/useGraphEdgeControls";

export type { GlobalGraphFilters };

interface GlobalGraphPanelProps {
  baseUrl: string;
  graph: GlobalGraphResponse | null;
  filters: GlobalGraphFilters;
  isLoading: boolean;
  errorMessage: string | null;
  availableSubjects: string[];
  availableTags: string[];
  onRetry: () => void;
  onFiltersChange: (next: GlobalGraphFilters) => void;
  onOpenNote: (noteId: string) => void;
  onCreateNote?: () => void;
}

export function GlobalGraphPanel({
  baseUrl,
  graph,
  filters,
  isLoading,
  errorMessage,
  availableSubjects,
  availableTags,
  onRetry,
  onFiltersChange,
  onOpenNote,
  onCreateNote,
}: GlobalGraphPanelProps) {
  const [insightNode, setInsightNode] = useState<LocalGraphNode | null>(null);
  const [nodeSearch, setNodeSearch] = useState("");
  const edgeControls = useGraphEdgeControls();
  const [canvasWidth, setCanvasWidth] = useState(800);
  const [canvasHeight, setCanvasHeight] = useState(600);
  const canvasAreaRef = useRef<HTMLDivElement>(null);

  function handleNodeClick(node: LocalGraphNode) {
    if (node.type === "note") {
      onOpenNote(String(node.metadata.note_id ?? node.id));
    } else {
      setInsightNode(node);
    }
  }

  useEffect(() => {
    const el = canvasAreaRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      if (rect.width > 0) setCanvasWidth(rect.width);
      if (rect.height > 0) setCanvasHeight(rect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const normalizedSearch = nodeSearch.trim().toLowerCase();

  // Find the first node whose label matches; highlight and zoom to it.
  // All nodes and edges stay visible so adjacency (related concepts) is preserved.
  const highlightNodeId = normalizedSearch && graph
    ? graph.nodes.find((n) => n.label.toLowerCase().includes(normalizedSearch))?.id
    : undefined;

  const nodeCount = graph?.nodes.length ?? 0;
  const edgeCount = graph?.edges.length ?? 0;
  const presentEdgeTypes = graph ? Array.from(new Set(graph.edges.map((e) => e.type))) : [];

  return (
    <div className="global-graph-view" aria-label="Global graph view">
      <aside className="global-graph-sidebar">
        <h2 className="global-graph-title">Knowledge Graph</h2>

        {/* Node search — pill bar, same pattern as notes sidebar */}
        <div className="notes-filter-search-wrap">
          <input
            className="notes-filter-input notes-filter-search-input"
            type="text"
            aria-label="Search nodes"
            placeholder="Search nodes…"
            value={nodeSearch}
            onChange={(e) => setNodeSearch(e.target.value)}
          />
        </div>

        {/* Subject + Tag — compact side-by-side pill comboboxes */}
        <div className="notes-filter-pair">
          <FilterCombobox
            label="Subject"
            value={filters.subject_id ?? ""}
            onChange={(v) => onFiltersChange({ ...filters, subject_id: v || undefined })}
            options={availableSubjects}
            placeholder="Subject"
          />
          <FilterCombobox
            label="Tag"
            value={filters.tag ?? ""}
            onChange={(v) => onFiltersChange({ ...filters, tag: v || undefined })}
            options={availableTags}
            placeholder="Tag"
          />
        </div>

        {/* Node + edge counts */}
        <div className="workspace-stat-grid global-graph-stats">
          <div className="workspace-stat-card">
            <span className="workspace-stat-label">Nodes</span>
            <span className="workspace-stat-value">{nodeCount}</span>
          </div>
          <div className="workspace-stat-card">
            <span className="workspace-stat-label">Edges</span>
            <span className="workspace-stat-value">{edgeCount}</span>
          </div>
        </div>

        {graph?.meta.truncated && (
          <p className="global-graph-truncated-note">
            Showing top {graph.meta.applied_filters.limit_nodes} nodes
          </p>
        )}

        {presentEdgeTypes.length > 0 && (
          <GraphLegend
            presentTypes={presentEdgeTypes}
            hidden={edgeControls.hidden}
            highlighted={edgeControls.highlighted}
            onToggleHidden={edgeControls.toggleHidden}
            onToggleHighlighted={edgeControls.toggleHighlighted}
          />
        )}
      </aside>

      <div className="global-graph-canvas-area" ref={canvasAreaRef}>
        {isLoading ? (
          <SkeletonGraph />
        ) : errorMessage ? (
          <ErrorMessage message={errorMessage} actionLabel="Retry" onAction={onRetry} />
        ) : !graph || nodeCount === 0 ? (
          <EmptyState
            icon="🕸️"
            title="No notes yet"
            description="Start creating notes to see your knowledge graph."
            actionLabel={onCreateNote ? "Create note" : undefined}
            onAction={onCreateNote}
          />
        ) : (
          <D3GraphCanvas
            nodes={graph.nodes}
            edges={graph.edges}
            highlightNodeId={highlightNodeId}
            width={canvasWidth}
            height={canvasHeight}
            onNodeClick={handleNodeClick}
            hiddenEdgeTypes={edgeControls.hidden}
            highlightedEdgeTypes={edgeControls.highlighted}
          />
        )}
      </div>

      {insightNode && (
        <ConceptInsightPanel
          node={insightNode}
          baseUrl={baseUrl}
          onClose={() => setInsightNode(null)}
          onOpenNote={(noteId) => {
            onOpenNote(noteId);
            setInsightNode(null);
          }}
        />
      )}
    </div>
  );
}
