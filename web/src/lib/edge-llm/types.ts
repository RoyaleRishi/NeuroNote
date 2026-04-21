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
