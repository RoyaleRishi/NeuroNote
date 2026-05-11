"use client";

import { useState } from "react";

import { D3GraphCanvas } from "./D3GraphCanvas";
import { ConceptInsightPanel } from "./ConceptInsightPanel";
import type { LocalGraphNode, LocalGraphResponse } from "../../../../shared/contracts/ts/v1/graph";
import { SkeletonGraph } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { ErrorMessage } from "../ui/ErrorMessage";

interface LocalGraphPanelProps {
  noteId: string;
  baseUrl: string;
  graph: LocalGraphResponse | null;
  isLoading: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  onOpenNote: (noteId: string) => void;
}

export function LocalGraphPanel({
  noteId,
  baseUrl,
  graph,
  isLoading,
  errorMessage,
  onRetry,
  onOpenNote,
}: LocalGraphPanelProps) {
  const [insightNode, setInsightNode] = useState<LocalGraphNode | null>(null);

  function handleNodeClick(node: LocalGraphNode) {
    if (node.type === "note") {
      onOpenNote(String(node.metadata.note_id ?? node.id));
    } else {
      setInsightNode(node);
    }
  }

  const nodeCount = graph?.nodes.length ?? 0;
  const edgeCount = graph?.edges.length ?? 0;

  if (isLoading) {
    return <SkeletonGraph />;
  }

  if (errorMessage) {
    return (
      <ErrorMessage
        message={errorMessage}
        actionLabel="Retry"
        onAction={onRetry}
      />
    );
  }

  return (
    <section className="local-graph-panel" aria-label="Local graph panel">
      <header className="local-graph-header">
        <h2>Local graph</h2>
      </header>

      {graph !== null && (
        <>
          {nodeCount === 0 ? (
            <EmptyState
              icon="🕸️"
              title="No connections yet"
              description="Add wiki links or process this note to discover relationships."
            />
          ) : (
            <D3GraphCanvas
              nodes={graph.nodes}
              edges={graph.edges}
              rootNodeId={noteId}
              height={400}
              ariaLabel="Local graph canvas"
              onNodeClick={handleNodeClick}
            />
          )}
        </>
      )}

      <div className="local-graph-summary">
        <p>{nodeCount} nodes · {edgeCount} edges</p>
      </div>

      {insightNode && (
        <ConceptInsightPanel
          node={insightNode}
          baseUrl={baseUrl}
          onClose={() => setInsightNode(null)}
          onOpenNote={onOpenNote}
        />
      )}
    </section>
  );
}
