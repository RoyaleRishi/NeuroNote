import type {
  GetNoteResponse,
  ListNotesResponse,
  SaveNoteRequest,
  SaveNoteResponse,
} from "../../../shared/contracts/ts/v1/note";
import type {
  ProcessNoteRequest,
  ProcessNoteResponse,
  ProcessStatusResponse,
} from "../../../shared/contracts/ts/v1/process";
import type {
  DeleteImageResponse,
  UploadImageRequest,
  UploadImageResponse,
} from "../../../shared/contracts/ts/v1/media";
import type { BacklinksResponse } from "../../../shared/contracts/ts/v1/backlink";
import type { BlockSearchResponse } from "../../../shared/contracts/ts/v1/block";
import type {
  LocalGraphResponse,
  GlobalGraphResponse,
  ConceptInsightResponse,
} from "../../../shared/contracts/ts/v1/graph";
import type { UserProfile } from "../../../shared/contracts/ts/v1/auth";

const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiClientError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown = null) {
    super(`Request failed with status ${status}`);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
  }
}

/** Resolve the API base URL from the environment. */
export function getBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

/** Concurrent refresh requests share a single in-flight promise. */
let refreshPromise: Promise<boolean> | null = null;

/** Hit /v1/auth/refresh to issue a new access cookie from the refresh cookie. */
async function tryRefreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  const base = getBaseUrl();
  refreshPromise = (async () => {
    try {
      const res = await fetch(`${base}/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      return res.ok;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

/** Check if a URL is an auth endpoint where 401 should not trigger a refresh loop. */
function isAuthUrl(url: string): boolean {
  return url.includes("/v1/auth/");
}

/**
 * fetch wrapper that sends cookies cross-origin, enforces a request timeout,
 * and transparently refreshes expired access tokens on 401.
 *
 * Pass signal: null to opt out of the timeout for a specific call (e.g. long uploads).
 */
async function apiFetch(
  url: string,
  options: RequestInit & { timeoutMs?: number } = {},
): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...rest } = options;

  const doFetch = async (): Promise<Response> => {
    let controller: AbortController | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let effectiveSignal: AbortSignal | undefined =
      signal as AbortSignal | undefined;

    if (timeoutMs > 0) {
      controller = new AbortController();
      timeoutId = setTimeout(() => controller!.abort(), timeoutMs);
      effectiveSignal = controller.signal;
    }

    try {
      return await fetch(url, {
        ...rest,
        credentials: "include",
        signal: effectiveSignal,
        headers: {
          ...(rest.headers as Record<string, string> | undefined),
        },
      });
    } finally {
      if (timeoutId !== null) clearTimeout(timeoutId);
    }
  };

  const response = await doFetch();

  // On 401, try refreshing the access token once and retry the request.
  // Skip the auth endpoints themselves to avoid loops.
  if (response.status === 401 && !isAuthUrl(url)) {
    const refreshed = await tryRefreshAccessToken();
    if (refreshed) {
      return doFetch();
    }
    // Refresh failed → user truly logged out. Bounce to login.
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      const next = encodeURIComponent(
        window.location.pathname + window.location.search,
      );
      window.location.href = `/login?next=${next}`;
    }
  }

  return response;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = null;
    }
    throw new ApiClientError(response.status, detail);
  }
  return (await response.json()) as T;
}

export async function saveNote(
  baseUrl: string,
  payload: SaveNoteRequest,
  signal?: AbortSignal,
): Promise<SaveNoteResponse> {
  const response = await apiFetch(`${baseUrl}/v1/notes/${payload.note_id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  return parseJsonResponse<SaveNoteResponse>(response);
}

export async function getNote(baseUrl: string, noteId: string): Promise<GetNoteResponse> {
  const response = await apiFetch(`${baseUrl}/v1/notes/${noteId}`);
  return parseJsonResponse<GetNoteResponse>(response);
}

export interface ListNotesQuery {
  limit?: number;
  offset?: number;
  search?: string;
  subject_id?: string;
  tag?: string;
  is_archived?: boolean;
  is_pinned?: boolean;
}

export async function listNotes(
  baseUrl: string,
  query: ListNotesQuery = {},
): Promise<ListNotesResponse> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) {
    params.set("limit", String(query.limit));
  }
  if (query.offset !== undefined) {
    params.set("offset", String(query.offset));
  }
  if (query.search) {
    params.set("search", query.search);
  }
  if (query.subject_id) {
    params.set("subject_id", query.subject_id);
  }
  if (query.tag) {
    params.set("tag", query.tag);
  }
  if (query.is_archived !== undefined) {
    params.set("is_archived", String(query.is_archived));
  }
  if (query.is_pinned !== undefined) {
    params.set("is_pinned", String(query.is_pinned));
  }

  const suffix = params.toString();
  const response = await apiFetch(`${baseUrl}/v1/notes${suffix ? `?${suffix}` : ""}`);
  return parseJsonResponse<ListNotesResponse>(response);
}

export async function deleteNote(baseUrl: string, noteId: string): Promise<void> {
  const response = await apiFetch(`${baseUrl}/v1/notes/${noteId}`, { method: "DELETE" });
  if (!response.ok) {
    throw new ApiClientError(response.status);
  }
}

export async function queueNoteProcessing(
  baseUrl: string,
  payload: ProcessNoteRequest,
): Promise<ProcessNoteResponse> {
  const response = await apiFetch(`${baseUrl}/v1/process-note`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse<ProcessNoteResponse>(response);
}

export async function fetchProcessingStatus(
  baseUrl: string,
  jobId: string,
): Promise<ProcessStatusResponse> {
  const response = await apiFetch(`${baseUrl}/v1/process-status/${jobId}`);
  return parseJsonResponse<ProcessStatusResponse>(response);
}

export async function uploadNoteImage(
  baseUrl: string,
  noteId: string,
  file: File,
): Promise<UploadImageResponse> {
  const raw = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < raw.length; index += 1) {
    binary += String.fromCharCode(raw[index] ?? 0);
  }
  const payload: UploadImageRequest = {
    note_id: noteId,
    filename: file.name || "image",
    mime_type: file.type || "application/octet-stream",
    content_base64: btoa(binary),
  };

  const response = await apiFetch(`${baseUrl}/v1/media/uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeoutMs: 60_000, // uploads can take longer
  });
  return parseJsonResponse<UploadImageResponse>(response);
}

export async function deleteNoteImage(baseUrl: string, assetId: string): Promise<DeleteImageResponse> {
  const response = await apiFetch(`${baseUrl}/v1/media/${assetId}`, {
    method: "DELETE",
  });
  return parseJsonResponse<DeleteImageResponse>(response);
}

export async function exportNoteMarkdown(baseUrl: string, noteId: string): Promise<Blob> {
  const response = await apiFetch(`${baseUrl}/v1/notes/${noteId}/export/markdown`);
  if (!response.ok) {
    throw new ApiClientError(response.status);
  }
  return response.blob();
}

export async function fetchNoteBacklinks(
  baseUrl: string,
  noteId: string,
): Promise<BacklinksResponse> {
  const response = await apiFetch(`${baseUrl}/v1/notes/${noteId}/backlinks`);
  return parseJsonResponse<BacklinksResponse>(response);
}

export async function searchBlocks(
  baseUrl: string,
  query: string,
  options: { note_id?: string; limit?: number } = {},
): Promise<BlockSearchResponse> {
  const params = new URLSearchParams();
  params.set("q", query);
  if (options.note_id) {
    params.set("note_id", options.note_id);
  }
  params.set("limit", String(options.limit ?? 8));
  const response = await apiFetch(`${baseUrl}/v1/blocks/search?${params.toString()}`);
  return parseJsonResponse<BlockSearchResponse>(response);
}

export interface LocalGraphQuery {
  max_hops?: number;
  limit_nodes?: number;
  min_confidence?: number;
  include_types?: string[];
}

export async function fetchLocalGraph(
  baseUrl: string,
  noteId: string,
  query: LocalGraphQuery = {},
): Promise<LocalGraphResponse> {
  const params = new URLSearchParams();
  if (query.max_hops !== undefined) {
    params.set("max_hops", String(query.max_hops));
  }
  if (query.limit_nodes !== undefined) {
    params.set("limit_nodes", String(query.limit_nodes));
  }
  if (query.min_confidence !== undefined) {
    params.set("min_confidence", String(query.min_confidence));
  }
  if (query.include_types && query.include_types.length > 0) {
    params.set("include_types", query.include_types.join(","));
  }

  const suffix = params.toString();
  const response = await apiFetch(
    `${baseUrl}/v1/graph/local/${noteId}${suffix ? `?${suffix}` : ""}`,
    { timeoutMs: 60_000 }, // graph requests can be slow on cold cache
  );
  return parseJsonResponse<LocalGraphResponse>(response);
}

export async function fetchConceptInsight(
  baseUrl: string,
  label: string,
  limitNotes = 10,
): Promise<ConceptInsightResponse> {
  const params = new URLSearchParams();
  params.set("label", label);
  params.set("limit_notes", String(limitNotes));
  const response = await apiFetch(
    `${baseUrl}/v1/concepts/insight?${params.toString()}`,
    { timeoutMs: 30_000 },
  );
  return parseJsonResponse<ConceptInsightResponse>(response);
}

// ── File import ───────────────────────────────────────────────────────────────

import type { ImportNoteRequest, ImportNoteResponse } from "../../../shared/contracts/ts/v1/import";

export async function importNote(
  baseUrl: string,
  payload: ImportNoteRequest,
): Promise<ImportNoteResponse> {
  const response = await apiFetch(`${baseUrl}/v1/notes/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse<ImportNoteResponse>(response);
}

interface GlobalGraphQuery {
  limit_nodes?: number;
  min_confidence?: number;
  include_types?: string[];
  subject_id?: string;
  tag?: string;
}

export async function fetchGlobalGraph(
  baseUrl: string,
  query: GlobalGraphQuery = {},
): Promise<GlobalGraphResponse> {
  const params = new URLSearchParams();
  if (query.limit_nodes !== undefined) params.set("limit_nodes", String(query.limit_nodes));
  if (query.min_confidence !== undefined) params.set("min_confidence", String(query.min_confidence));
  if (query.include_types && query.include_types.length > 0) params.set("include_types", query.include_types.join(","));
  if (query.subject_id) params.set("subject_id", query.subject_id);
  if (query.tag) params.set("tag", query.tag);
  const suffix = params.toString();
  const response = await apiFetch(
    `${baseUrl}/v1/graph/global${suffix ? `?${suffix}` : ""}`,
    { timeoutMs: 60_000 },
  );
  return parseJsonResponse<GlobalGraphResponse>(response);
}

// ── Auth ─────────────────────────────────────────────────────────────────────

/** Fetch the currently authenticated user profile, or null if not logged in. */
export async function fetchCurrentUser(): Promise<UserProfile | null> {
  const base = getBaseUrl();
  const res = await apiFetch(`${base}/v1/auth/me`);
  if (res.status === 401) return null;
  return parseJsonResponse<UserProfile>(res);
}

/** Log the current user out by clearing server-side auth cookies. */
export async function logoutUser(): Promise<void> {
  const base = getBaseUrl();
  await apiFetch(`${base}/v1/auth/logout`, { method: "POST" });
}

// ── Preferences ─────────────────────────────────────────────────────────────

import type {
  UserPreferences,
  UpdatePreferencesRequest,
  TestConnectionResponse,
} from "../../../shared/contracts/ts/v1/preferences";

export type { UserPreferences, UpdatePreferencesRequest, TestConnectionResponse };

/** Fetch the user's preferences (with defaults for unset keys). */
export async function fetchPreferences(): Promise<UserPreferences> {
  const base = getBaseUrl();
  const res = await apiFetch(`${base}/v1/preferences`);
  return parseJsonResponse<UserPreferences>(res);
}

/** Partial update of user preferences. */
export async function updatePreferences(
  payload: UpdatePreferencesRequest,
): Promise<UserPreferences> {
  const base = getBaseUrl();
  const res = await apiFetch(`${base}/v1/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse<UserPreferences>(res);
}

/**
 * Validate the currently saved cloud LLM config by making a small completion
 * call against the user's configured base_url + model + key.  Used by the
 * UserMenu after Save to surface invalid credentials to the user.
 */
export async function testLlmConnection(): Promise<TestConnectionResponse> {
  const base = getBaseUrl();
  const res = await apiFetch(`${base}/v1/preferences/test-connection`, {
    method: "POST",
  });
  return parseJsonResponse<TestConnectionResponse>(res);
}
