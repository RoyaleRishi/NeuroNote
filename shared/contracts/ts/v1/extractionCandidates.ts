/** Shared contracts for POST /v1/extract-candidates. */

export interface ExtractCandidatesRequest {
  note_id: string;
  title: string;
  content_text: string;
  content_hash: string;
}

export interface ExtractCandidatesResponse {
  candidates: string[];
  content_hash: string;
}
