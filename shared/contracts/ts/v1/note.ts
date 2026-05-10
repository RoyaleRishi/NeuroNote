export interface SaveNoteRequest {
  note_id: string;
  note_title: string;
  subject_id: string;
  tags: string[];
  is_pinned: boolean;
  is_archived: boolean;
  content_json: Record<string, unknown>;
  content_text: string;
  updated_at: string;
}

export interface SaveNoteResponse {
  note_id: string;
  saved_at: string;
  version: number;
  content_hash: string;
}

export interface GetNoteResponse {
  note_id: string;
  note_title: string;
  subject_id: string;
  tags: string[];
  is_pinned: boolean;
  is_archived: boolean;
  content_json: Record<string, unknown>;
  content_text: string;
  content_hash: string;
  updated_at: string;
  version: number;
}

export interface NoteSummary {
  note_id: string;
  note_title: string;
  subject_id: string;
  tags: string[];
  is_pinned: boolean;
  is_archived: boolean;
  content_text: string;
  updated_at: string;
  version: number;
}

export interface ListNotesResponse {
  items: NoteSummary[];
  total: number;
}
