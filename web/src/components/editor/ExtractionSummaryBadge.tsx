"use client";

import { useEffect, useState } from "react";
import type { ExtractionSummary } from "../../../../shared/contracts/ts/v1/process";

interface ExtractionSummaryBadgeProps {
  summary: ExtractionSummary | null;
  autoDismissMs?: number;
}

/** Displays extraction results after NLP processing completes. Auto-dismisses. */
export function ExtractionSummaryBadge({
  summary,
  autoDismissMs = 8000,
}: ExtractionSummaryBadgeProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!summary) {
      setVisible(false);
      return;
    }
    setVisible(true);
    const timer = setTimeout(() => setVisible(false), autoDismissMs);
    return () => clearTimeout(timer);
  }, [summary, autoDismissMs]);

  if (!visible || !summary) return null;

  const parts: string[] = [];
  if (summary.entity_count > 0) parts.push(`${summary.entity_count} concept${summary.entity_count !== 1 ? "s" : ""}`);
  if (summary.relation_count > 0) parts.push(`${summary.relation_count} relation${summary.relation_count !== 1 ? "s" : ""}`);

  if (parts.length === 0) return null;

  return (
    <button
      type="button"
      className="extraction-summary-badge"
      onClick={() => setVisible(false)}
      title="Click to dismiss"
      data-testid="extraction-summary-badge"
    >
      <span className="extraction-summary-counts">{parts.join(" \u00b7 ")}</span>
      {summary.top_entities.length > 0 && (
        <span className="extraction-summary-entities">
          {summary.top_entities.slice(0, 3).map((entity) => (
            <span key={entity} className="extraction-entity-pill">{entity}</span>
          ))}
        </span>
      )}
    </button>
  );
}
