import type { APIRequestContext } from "@playwright/test";

/**
 * Helpers for creating and cleaning up notes via the public REST API.
 *
 * Tests that mutate workspace state should drive note creation through
 * these helpers (rather than the editor UI) so setup cost is dominated by
 * a single round-trip per fixture, and `afterEach` cleanup is trivial.
 */
const API_BASE_URL = process.env.E2E_API_BASE_URL ?? "http://localhost:8000";

export interface CreateNoteOptions {
  title: string;
  content_text: string;
  subject_id?: string;
  tags?: string[];
}

/** A random 6-char suffix usable to namespace test resources. */
export function randomSuffix(): string {
  return Math.random().toString(36).slice(2, 8);
}

/** Build a unique title prefixed with the test scope. */
export function uniqueTitle(scope: string): string {
  return `e2e-${scope}-${Date.now()}-${randomSuffix()}`;
}

function makeNoteId(): string {
  // Mirrors web/src/lib/utils/note-id.ts shape (`note_<random>`).  The
  // backend only requires a stable string, so a random hex suffix is fine.
  return `note_${Date.now().toString(36)}${randomSuffix()}`;
}

function buildContentJson(text: string): Record<string, unknown> {
  // TipTap doc with a single paragraph block. The backend doesn't validate
  // the schema deeply, but matching the real shape keeps the pipeline happy.
  return {
    type: "doc",
    content: [
      {
        type: "paragraph",
        content: text ? [{ type: "text", text }] : [],
      },
    ],
  };
}

/**
 * Creates a note via PUT /v1/notes/{id}. Returns the note id.
 *
 * The cookies set by `loginAsDev` (via `page.request`) are shared with
 * the page's request context, so this works without re-authenticating.
 */
export async function createNote(
  request: APIRequestContext,
  options: CreateNoteOptions,
): Promise<string> {
  const noteId = makeNoteId();
  const response = await request.put(`${API_BASE_URL}/v1/notes/${noteId}`, {
    data: {
      note_id: noteId,
      note_title: options.title,
      subject_id: options.subject_id ?? "inbox",
      tags: options.tags ?? [],
      is_pinned: false,
      is_archived: false,
      content_json: buildContentJson(options.content_text),
      content_text: options.content_text,
      updated_at: new Date().toISOString(),
    },
  });
  if (!response.ok()) {
    throw new Error(
      `createNote failed: ${response.status()} ${await response.text()}`,
    );
  }
  return noteId;
}

/** Deletes a note. Swallows 404s so cleanup is idempotent. */
export async function deleteNote(
  request: APIRequestContext,
  noteId: string,
): Promise<void> {
  const response = await request.delete(`${API_BASE_URL}/v1/notes/${noteId}`);
  if (!response.ok() && response.status() !== 404) {
    // Do not throw — afterEach should never mask a test failure.
    // eslint-disable-next-line no-console
    console.warn(
      `deleteNote(${noteId}) returned ${response.status()}: ${await response.text()}`,
    );
  }
}

/** Convenience: best-effort cleanup of multiple ids. */
export async function deleteNotes(
  request: APIRequestContext,
  noteIds: string[],
): Promise<void> {
  for (const id of noteIds) {
    await deleteNote(request, id);
  }
}

/**
 * Triggers the deterministic NLP pipeline for a note and waits for the job
 * to reach `completed`.  Necessary because POST /v1/notes/{id} alone does
 * not enqueue extraction — that happens client-side in the editor.
 */
export async function processNoteAndWait(
  request: APIRequestContext,
  noteId: string,
  contentText: string,
  timeoutMs = 90_000,
): Promise<void> {
  const note = await request.get(`${API_BASE_URL}/v1/notes/${noteId}`);
  if (!note.ok()) throw new Error(`note ${noteId} not found`);
  const body = (await note.json()) as { content_hash: string; updated_at: string };

  const enqueue = await request.post(`${API_BASE_URL}/v1/process-note`, {
    data: {
      note_id: noteId,
      content_text: contentText,
      content_hash: body.content_hash,
      updated_at: body.updated_at,
    },
  });
  if (!enqueue.ok()) {
    throw new Error(`process-note failed: ${enqueue.status()} ${await enqueue.text()}`);
  }
  const { job_id: jobId } = (await enqueue.json()) as { job_id: string };

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const r = await request.get(`${API_BASE_URL}/v1/process-status/${jobId}`);
    if (r.ok()) {
      const status = (await r.json()) as { status: string };
      if (status.status === "completed") return;
      if (status.status === "failed") {
        throw new Error(`processing job ${jobId} failed`);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new Error(`processing job ${jobId} did not complete within ${timeoutMs}ms`);
}

export { API_BASE_URL };
