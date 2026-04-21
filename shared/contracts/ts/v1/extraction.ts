/** Shared contracts for edge-mode extraction endpoints. */

// ── POST /v1/extraction-results ─────────────────────────────────────────────

export interface EdgeConceptItem {
  text: string;
  confidence: number;
}

export interface EdgeRelationItem {
  source: string;
  type: string;
  target: string;
  confidence: number;
}

export interface SubmitExtractionResultsRequest {
  note_id: string;
  content_hash: string;
  concepts: EdgeConceptItem[];
  relations: EdgeRelationItem[];
  summary: string;
}

export interface SubmitExtractionResultsResponse {
  note_id: string;
  entity_count: number;
  relation_count: number;
  synced: boolean;
}

// ── POST /v1/meta-classification-results ────────────────────────────────────

export interface SynonymPair {
  a: string;
  b: string;
}

export interface SubtopicPair {
  specific: string;
  broader: string;
}

export interface SubmitMetaClassificationRequest {
  synonym_pairs: SynonymPair[];
  subtopic_pairs: SubtopicPair[];
  classified_concepts: string[];
}

export interface SubmitMetaClassificationResponse {
  synonym_edges_written: number;
  subtopic_edges_written: number;
}

// ── GET /v1/concepts/insight-context ────────────────────────────────────────

export interface InsightContextNote {
  note_id: string;
  title: string;
  excerpt: string;
}

export interface InsightContextResponse {
  concept_label: string;
  notes: InsightContextNote[];
  total_notes: number;
}

// ── GET /v1/concepts/known ──────────────────────────────────────────────────

export interface KnownConceptsResponse {
  concepts: string[];
}
