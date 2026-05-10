"use client";

import { useEffect, useRef, useState } from "react";

import { fetchConceptInsight } from "../../lib/api-client";
import type {
  ConceptInsightResponse,
  ConceptLearningLink,
  ConceptNoteRef,
  LocalGraphNode,
} from "../../../../shared/contracts/ts/v1/graph";

interface ConceptInsightPanelProps {
  node: LocalGraphNode;
  baseUrl: string;
  onClose: () => void;
  onOpenNote: (noteId: string) => void;
}

export function ConceptInsightPanel({
  node,
  baseUrl,
  onClose,
  onOpenNote,
}: ConceptInsightPanelProps) {
  const [data, setData] = useState<ConceptInsightResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [linksOpen, setLinksOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setData(null);
    fetchConceptInsight(baseUrl, node.label, 10)
      .then(setData)
      .catch(() => setError("Could not load insight. Please try again."))
      .finally(() => setLoading(false));
  }, [baseUrl, node.label]);

  // Close on Escape
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // Close on click outside
  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [onClose]);

  return (
    <div className="concept-insight-overlay" role="dialog" aria-modal="true" aria-label={`Insight: ${node.label}`}>
      <div ref={panelRef} className="concept-insight-panel">
        {/* ── Header ── */}
        <div className="concept-insight-header">
          <div className="concept-insight-header-left">
            <span className="concept-insight-type-badge">{node.type}</span>
            <h2 className="concept-insight-title">{node.label}</h2>
          </div>
          <button
            type="button"
            className="concept-insight-close"
            aria-label="Close insight panel"
            onClick={onClose}
          >
            ×
          </button>
        </div>

        {/* ── Body ── */}
        <div className="concept-insight-body">
          {loading ? (
            <LoadingSkeleton />
          ) : error ? (
            <p className="concept-insight-error">{error}</p>
          ) : data ? (
            <>
              <RelatedNotes refs={data.note_refs} onOpenNote={onOpenNote} onClose={onClose} />
              <InsightSection
                insight={data.insight}
                insightError={data.insight_error ?? null}
              />
              {data.learning_links.length > 0 && (
                <LearningLinks
                  links={data.learning_links}
                  open={linksOpen}
                  onToggle={() => setLinksOpen((v) => !v)}
                />
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function RelatedNotes({
  refs,
  onOpenNote,
  onClose,
}: {
  refs: ConceptNoteRef[];
  onOpenNote: (noteId: string) => void;
  onClose: () => void;
}) {
  if (refs.length === 0) {
    return (
      <div className="concept-insight-section">
        <h3 className="concept-insight-section-title">Related notes</h3>
        <p className="concept-insight-empty">No notes mention this concept yet.</p>
      </div>
    );
  }
  return (
    <div className="concept-insight-section">
      <h3 className="concept-insight-section-title">
        Related notes
        <span className="concept-insight-count">{refs.length}</span>
      </h3>
      <ul className="concept-insight-note-list">
        {refs.map((ref) => (
          <li key={ref.note_id}>
            <button
              type="button"
              className="concept-insight-note-card"
              onClick={() => {
                onOpenNote(ref.note_id);
                onClose();
              }}
            >
              <span className="concept-insight-note-title">{ref.note_title}</span>
              <span className="concept-insight-note-snippet">{ref.snippet}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function InsightSection({
  insight,
  insightError,
}: {
  insight: string | null;
  insightError: string | null;
}) {
  return (
    <div className="concept-insight-section">
      <h3 className="concept-insight-section-title">
        AI insight
        <span className="concept-insight-grounded-badge">grounded in your notes</span>
      </h3>
      {insight ? (
        <div className="concept-insight-text">{insight}</div>
      ) : insightError ? (
        // The backend reported a concrete reason — surface it verbatim so
        // the user can fix their model/key/base-url instead of guessing.
        <p className="concept-insight-error" role="alert">
          AI insight unavailable: {insightError}
        </p>
      ) : (
        <p className="concept-insight-no-llm">
          Configure a cloud AI key in your user menu to enable AI insights.
        </p>
      )}
    </div>
  );
}

function LearningLinks({
  links,
  open,
  onToggle,
}: {
  links: ConceptLearningLink[];
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="concept-insight-section">
      <button
        type="button"
        className="concept-insight-links-toggle"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span>Further learning</span>
        <span className="concept-insight-links-chevron">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <>
          <p className="concept-insight-disclaimer">
            AI-suggested resources — verify before visiting.
          </p>
          <ul className="concept-insight-link-list">
            {links.map((link) => (
              <li key={link.url} className="concept-insight-link-item">
                <a
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="concept-insight-link-title"
                >
                  {link.title}
                </a>
                <span className="concept-insight-link-desc">{link.description}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="concept-insight-skeleton" aria-label="Loading insight…">
      <div className="concept-insight-section">
        <div className="concept-insight-skeleton-title skeleton" />
        <div className="concept-insight-skeleton-card skeleton" />
        <div className="concept-insight-skeleton-card skeleton" />
      </div>
      <div className="concept-insight-section">
        <div className="concept-insight-skeleton-title skeleton" />
        <div className="concept-insight-skeleton-line skeleton" />
        <div className="concept-insight-skeleton-line skeleton" style={{ width: "85%" }} />
        <div className="concept-insight-skeleton-line skeleton" style={{ width: "70%" }} />
      </div>
    </div>
  );
}
