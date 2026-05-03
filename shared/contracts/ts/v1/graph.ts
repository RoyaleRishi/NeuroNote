export interface LocalGraphFilters {
  max_hops: number;
  limit_nodes: number;
  min_confidence: number;
  include_types: string[];
}

export interface LocalGraphNode {
  id: string;
  type: string;
  label: string;
  confidence: number | null;
  source_note_id: string | null;
  metadata: Record<string, unknown>;
}

export interface LocalGraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: number | null;
  source_note_id: string | null;
}

export interface LocalGraphMeta {
  root_note_id: string;
  applied_filters: LocalGraphFilters;
  truncated: boolean;
}

export interface LocalGraphResponse {
  nodes: LocalGraphNode[];
  edges: LocalGraphEdge[];
  meta: LocalGraphMeta;
}

export interface GlobalGraphFilters {
  limit_nodes: number;
  min_confidence: number;
  include_types: string[];
  subject_id?: string;
  tag?: string;
}

export interface GlobalGraphMeta {
  total_notes: number;
  applied_filters: GlobalGraphFilters;
  truncated: boolean;
}

export interface GlobalGraphResponse {
  nodes: LocalGraphNode[];
  edges: LocalGraphEdge[];
  meta: GlobalGraphMeta;
}

export interface ConceptNoteRef {
  note_id: string;
  note_title: string;
  snippet: string;
}

export interface ConceptLearningLink {
  title: string;
  url: string;
  description: string;
}

export interface ConceptInsightResponse {
  concept_label: string;
  notes_found: number;
  note_refs: ConceptNoteRef[];
  insight: string | null;
  learning_links: ConceptLearningLink[];
  generated_at: string;
}
