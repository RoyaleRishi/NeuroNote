export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface ProcessNoteRequest {
  note_id: string;
  content_text: string;
  content_hash: string;
  updated_at: string;
}

export interface ProcessNoteResponse {
  job_id: string;
  status: "queued";
}

export interface ExtractionSummary {
  entity_count: number;
  relation_count: number;
  keyphrase_count: number;
  top_entities: string[];
}

export interface ProcessStatusResponse {
  job_id: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  error?: string | null;
  extraction_summary?: ExtractionSummary | null;
}
