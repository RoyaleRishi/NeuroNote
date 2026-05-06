/** Messages between main thread and Web Worker. */

export type WorkerRequest =
  | { type: "init" }
  | { type: "generate-insight"; payload: InsightRequest };

export type WorkerResponse =
  | { type: "init-progress"; progress: { text: string; progress: number } }
  | { type: "ready" }
  | { type: "error"; error: string }
  | { type: "generate-insight-result"; payload: InsightResult };

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

export interface SummaryRequest {
  title: string;
  content: string;
  /** The deduped canonical concept list — used to ground the summary. */
  concepts: string[];
}
