"use client";

import { useEffect, useRef, useState } from "react";

import { fetchConceptInsight, fetchInsightContext } from "../../lib/api-client";
import { usePreferences } from "../../lib/hooks/usePreferences";
import { getEngine } from "../../lib/edge-llm/model-manager";
import { useDismissable } from "../../lib/hooks/useDismissable";
import type {
  ConceptInsightResponse,
  ConceptLearningLink,
  ConceptNoteRef,
  InsightContextNote,
  LocalGraphNode,
} from "../../../../shared/contracts/ts/v1/graph";

const EDGE_SYSTEM_PROMPT = `You are a knowledge synthesis assistant. Generate an insight about a concept based \
SOLELY on the user's own notes.

Rules:
- The insight must draw only from the provided notes. Do not add external knowledge.
- Reference note titles explicitly, e.g. "In your note 'Title'...".
- Keep the insight to 2–3 focused paragraphs.
- For learning_links: suggest 3–4 genuinely reputable URLs (Wikipedia, official \
documentation, well-known academic sources). Use only real, widely-known URLs.

Respond ONLY with valid JSON in exactly this shape (no markdown fences):
{
  "insight": "...",
  "learning_links": [
    {"title": "...", "url": "https://...", "description": "..."}
  ]
}`;

interface ConceptInsightPanelProps {
  node: LocalGraphNode;
  baseUrl: string;
  onClose: () => void;
  onOpenNote: (noteId: string) => void;
}

type EdgeStatus = "loading-model" | "generating" | "done" | "error";

interface PanelData {
  noteRefs: ConceptNoteRef[];
  insight: string | null;
  insightError: string | null;
  learningLinks: ConceptLearningLink[];
}

export function ConceptInsightPanel({
  node,
  baseUrl,
  onClose,
  onOpenNote,
}: ConceptInsightPanelProps) {
  const { prefs } = usePreferences();
  const llmMode = prefs?.llm_mode ?? "edge";

  const [data, setData] = useState<PanelData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [edgeStatus, setEdgeStatus] = useState<EdgeStatus | null>(null);
  const [linksOpen, setLinksOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setData(null);
    setEdgeStatus(null);

    if (llmMode === "edge") {
      void runEdgeInsight();
    } else {
      void runCloudInsight();
    }

    async function runCloudInsight() {
      try {
        const resp: ConceptInsightResponse = await fetchConceptInsight(baseUrl, node.label, 10);
        setData({
          noteRefs: resp.note_refs,
          insight: resp.insight,
          insightError: resp.insight_error,
          learningLinks: resp.learning_links,
        });
      } catch {
        setError("Could not load insight. Please try again.");
      } finally {
        setLoading(false);
      }
    }

    async function runEdgeInsight() {
      try {
        const context = await fetchInsightContext(baseUrl, node.label, 10);
        const noteRefs: ConceptNoteRef[] = context.notes.map((n: InsightContextNote) => ({
          note_id: n.note_id,
          note_title: n.title,
          snippet: n.excerpt,
        }));

        const engine = getEngine();
        if (!engine) {
          setData({ noteRefs, insight: null, insightError: null, learningLinks: [] });
          setEdgeStatus("loading-model");
          setLoading(false);
          return;
        }

        setEdgeStatus("generating");
        const noteContext = context.notes
          .map((n: InsightContextNote, i: number) => `[Note ${i + 1}: '${n.title}']\n${n.excerpt}`)
          .join("\n\n---\n\n");

        const response = await engine.chat.completions.create({
          messages: [
            { role: "system", content: EDGE_SYSTEM_PROMPT },
            {
              role: "user",
              content: `Concept: "${node.label}"\n\nUser notes:\n\n${noteContext}`,
            },
          ],
          max_tokens: 1024,
        });

        const raw = (response.choices[0]?.message.content ?? "").trim();
        let parsed: { insight?: string; learning_links?: ConceptLearningLink[] } = {};
        try {
          parsed = JSON.parse(raw) as typeof parsed;
        } catch {
          // Non-JSON fallback: treat the whole response as plain insight text
          parsed = { insight: raw || null, learning_links: [] };
        }

        const links: ConceptLearningLink[] = (parsed.learning_links ?? []).filter(
          (l): l is ConceptLearningLink =>
            typeof l === "object" && l !== null && "title" in l && "url" in l && "description" in l,
        );
        setData({ noteRefs, insight: parsed.insight ?? null, insightError: null, learningLinks: links });
        setEdgeStatus("done");
      } catch {
        setEdgeStatus("error");
        setData((prev) => prev ?? { noteRefs: [], insight: null, insightError: null, learningLinks: [] });
      } finally {
        setLoading(false);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl, node.label, llmMode]);

  useDismissable(panelRef, true, onClose);

  return (
    <div className="concept-insight-overlay" role="dialog" aria-modal="true" aria-label={`Insight: ${node.label}`}>
      <div ref={panelRef} className="concept-insight-panel">
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

        <div className="concept-insight-body">
          {loading ? (
            <LoadingSkeleton />
          ) : error ? (
            <p className="concept-insight-error">{error}</p>
          ) : data ? (
            <>
              <RelatedNotes refs={data.noteRefs} onOpenNote={onOpenNote} onClose={onClose} />
              <InsightSection
                insight={data.insight}
                insightError={data.insightError}
                llmMode={llmMode}
                edgeStatus={edgeStatus}
              />
              {data.learningLinks.length > 0 && (
                <LearningLinks
                  links={data.learningLinks}
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
  llmMode,
  edgeStatus,
}: {
  insight: string | null;
  insightError: string | null;
  llmMode: "edge" | "cloud";
  edgeStatus: EdgeStatus | null;
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
        <p className="concept-insight-error" role="alert">
          AI insight unavailable: {insightError}
        </p>
      ) : llmMode === "edge" ? (
        edgeStatus === "loading-model" ? (
          <p className="concept-insight-no-llm">
            On-device AI is still loading — insight will appear once the model finishes downloading.
          </p>
        ) : edgeStatus === "error" ? (
          <p className="concept-insight-error" role="alert">
            On-device AI insight unavailable. The model may have encountered an error.
          </p>
        ) : (
          <p className="concept-insight-no-llm">
            On-device AI is still loading — insight will appear once the model finishes downloading.
          </p>
        )
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
