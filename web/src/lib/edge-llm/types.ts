/** Messages between main thread and Web Worker. */

export type WorkerRequest =
  | { type: "init" }
  | { type: "extract"; payload: ExtractionRequest }
  | { type: "classify-meta"; payload: MetaClassificationRequest }
  | { type: "generate-insight"; payload: InsightRequest };

export type WorkerResponse =
  | { type: "init-progress"; progress: { text: string; progress: number } }
  | { type: "ready" }
  | { type: "error"; error: string }
  | { type: "extract-result"; payload: ExtractionResult }
  | { type: "classify-meta-result"; payload: MetaClassificationResult }
  | { type: "generate-insight-result"; payload: InsightResult };

export interface ExtractionRequest {
  title: string;
  content: string;
  knownConcepts: string[];
}

export interface ExtractionResult {
  concepts: Array<{ text: string; confidence: number }>;
  relations: Array<{
    source: string;
    type: string;
    target: string;
    confidence: number;
  }>;
  summary: string;
}

export interface MetaClassificationRequest {
  concepts: string[];
  knownConcepts: string[];
}

export interface MetaClassificationResult {
  synonymPairs: Array<{ a: string; b: string }>;
  subtopicPairs: Array<{ specific: string; broader: string }>;
}

export interface InsightRequest {
  conceptLabel: string;
  noteContexts: Array<{ noteId: string; title: string; excerpt: string }>;
}

export interface InsightResult {
  insight: string;
  learningLinks: Array<{
    title: string;
    url: string;
    description: string;
  }>;
}

export interface NoteChunk {
  /** 0-based chunk index. */
  index: number;
  /** The chunk's text content. */
  text: string;
  /** Character offset of chunk start in the full note. */
  startOffset: number;
}

export interface ChunkExtractionRequest {
  chunk: NoteChunk;
  candidates: string[];
  knownConcepts: string[];
}

export type RelationType =
  | "IS_A"
  | "PART_OF"
  | "CAUSES"
  | "CONTRASTS_WITH"
  | "USES"
  | "PRODUCES"
  | "RELATED_TO";

export interface ChunkExtractionResult {
  /** Indices of candidates the LLM kept as real concepts. */
  keep: number[];
  /** Tuples of (sourceIdx, relationType, targetIdx) — both indices into candidates. */
  relations: Array<[number, RelationType, number]>;
}

export interface CanonicalConcept {
  text: string;
  confidence: number;
  sources: number[];
}

export interface SummaryRequest {
  title: string;
  content: string;
  /** The deduped canonical concept list — used to ground the summary. */
  concepts: string[];
}
