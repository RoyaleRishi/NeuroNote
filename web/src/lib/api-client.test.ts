import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiClientError,
  deleteNote,
  exportNoteMarkdown,
  fetchLocalGraph,
  fetchNoteBacklinks,
  getNote,
  listNotes,
  saveNote,
  searchBlocks,
} from "./api-client";

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockReset();
});

function makeResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    blob: () => Promise.resolve(new Blob([JSON.stringify(body)])),
  } as Response);
}

function makeNoContentResponse(status = 204): Promise<Response> {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.reject(new SyntaxError("No content")),
    blob: () => Promise.resolve(new Blob()),
  } as Response);
}

// ─── saveNote ────────────────────────────────────────────────────────────────

describe("saveNote", () => {
  const basePayload = {
    note_id: "note-1",
    note_title: "Test Note",
    subject_id: "inbox",
    tags: ["a"],
    is_pinned: false,
    is_archived: false,
    content_json: { type: "doc", content: [] },
    content_text: "hello",
    updated_at: "2026-01-01T00:00:00Z",
  };

  it("sends PUT with JSON body to correct URL", async () => {
    mockFetch.mockReturnValue(
      makeResponse({ note_id: "note-1", saved_at: "2026-01-01T00:00:01Z", version: 2 }),
    );
    await saveNote("http://localhost:8000", basePayload);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/notes/note-1",
      expect.objectContaining({
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(basePayload),
      }),
    );
  });

  it("returns parsed SaveNoteResponse", async () => {
    const responseBody = { note_id: "note-1", saved_at: "2026-01-01T00:00:01Z", version: 2 };
    mockFetch.mockReturnValue(makeResponse(responseBody));
    const result = await saveNote("http://localhost:8000", basePayload);
    expect(result).toEqual(responseBody);
  });

  it("throws ApiClientError on 409", async () => {
    const detail = { message: "Title already exists" };
    mockFetch.mockReturnValue(makeResponse(detail, 409));
    await expect(saveNote("http://localhost:8000", basePayload)).rejects.toSatisfy(
      (err: unknown) =>
        err instanceof ApiClientError && err.status === 409 && err.detail === detail,
    );
  });

  it("throws ApiClientError on 500", async () => {
    const detail = { message: "Internal server error" };
    mockFetch.mockReturnValue(makeResponse(detail, 500));
    await expect(saveNote("http://localhost:8000", basePayload)).rejects.toSatisfy(
      (err: unknown) => err instanceof ApiClientError && err.status === 500,
    );
  });
});

// ─── getNote ─────────────────────────────────────────────────────────────────

describe("getNote", () => {
  const noteResponse = {
    note_id: "note-2",
    note_title: "Fetched Note",
    subject_id: "work",
    tags: ["ts"],
    is_pinned: false,
    is_archived: false,
    content_json: { type: "doc", content: [] },
    content_text: "body text",
    updated_at: "2026-01-02T00:00:00Z",
    version: 1,
  };

  it("sends GET to correct URL", async () => {
    mockFetch.mockReturnValue(makeResponse(noteResponse));
    await getNote("http://localhost:8000", "note-2");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/notes/note-2",
      expect.any(Object),
    );
  });

  it("returns GetNoteResponse", async () => {
    mockFetch.mockReturnValue(makeResponse(noteResponse));
    const result = await getNote("http://localhost:8000", "note-2");
    expect(result).toEqual(noteResponse);
  });

  it("throws ApiClientError with status on 404", async () => {
    mockFetch.mockReturnValue(makeResponse({ detail: "Not found" }, 404));
    await expect(getNote("http://localhost:8000", "missing-note")).rejects.toSatisfy(
      (err: unknown) => err instanceof ApiClientError && err.status === 404,
    );
  });
});

// ─── listNotes ───────────────────────────────────────────────────────────────

describe("listNotes", () => {
  const listResponse = { items: [], total: 0 };

  it("sends GET without query params when no filters provided", async () => {
    mockFetch.mockReturnValue(makeResponse(listResponse));
    await listNotes("http://localhost:8000");
    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toBe("http://localhost:8000/v1/notes");
    expect(calledUrl).not.toContain("?");
  });

  it("includes search param", async () => {
    mockFetch.mockReturnValue(makeResponse(listResponse));
    await listNotes("http://localhost:8000", { search: "foo" });
    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain("search=foo");
  });

  it("includes all filter params", async () => {
    mockFetch.mockReturnValue(makeResponse(listResponse));
    await listNotes("http://localhost:8000", {
      limit: 10,
      offset: 20,
      subject_id: "work",
      tag: "ts",
      is_archived: false,
      is_pinned: true,
    });
    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain("limit=10");
    expect(calledUrl).toContain("offset=20");
    expect(calledUrl).toContain("subject_id=work");
    expect(calledUrl).toContain("tag=ts");
    expect(calledUrl).toContain("is_archived=false");
    expect(calledUrl).toContain("is_pinned=true");
  });
});

// ─── deleteNote ──────────────────────────────────────────────────────────────

describe("deleteNote", () => {
  it("sends DELETE and resolves on 204", async () => {
    mockFetch.mockReturnValue(makeNoContentResponse(204));
    await expect(deleteNote("http://localhost:8000", "note-3")).resolves.toBeUndefined();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/notes/note-3",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("throws ApiClientError on 404", async () => {
    mockFetch.mockReturnValue(makeNoContentResponse(404));
    await expect(deleteNote("http://localhost:8000", "missing")).rejects.toSatisfy(
      (err: unknown) => err instanceof ApiClientError && err.status === 404,
    );
  });
});

// ─── ApiClientError detail parsing ───────────────────────────────────────────

describe("ApiClientError", () => {
  it("includes detail from response body on error", async () => {
    const detail = { message: "conflict detected" };
    mockFetch.mockReturnValue(makeResponse(detail, 409));
    let caught: unknown;
    try {
      await getNote("http://localhost:8000", "note-x");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiClientError);
    expect((caught as ApiClientError).detail).toEqual(detail);
  });

  it("detail is null when response body is not valid JSON", async () => {
    // Simulate a response whose json() rejects (non-JSON body)
    mockFetch.mockReturnValue(
      Promise.resolve({
        ok: false,
        status: 503,
        json: () => Promise.reject(new SyntaxError("Unexpected token")),
        blob: () => Promise.resolve(new Blob()),
      } as Response),
    );
    let caught: unknown;
    try {
      await getNote("http://localhost:8000", "note-x");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiClientError);
    expect((caught as ApiClientError).status).toBe(503);
    expect((caught as ApiClientError).detail).toBeNull();
  });
});

// ─── fetchNoteBacklinks ───────────────────────────────────────────────────────

describe("fetchNoteBacklinks", () => {
  it("constructs correct URL", async () => {
    mockFetch.mockReturnValue(makeResponse({ note_id: "note-1", items: [] }));
    await fetchNoteBacklinks("http://localhost:8000", "note-1");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/notes/note-1/backlinks",
      expect.any(Object),
    );
  });
});

// ─── searchBlocks ─────────────────────────────────────────────────────────────

describe("searchBlocks", () => {
  it("includes q, limit, and note_id params", async () => {
    mockFetch.mockReturnValue(makeResponse({ items: [] }));
    await searchBlocks("http://localhost:8000", "hello", { note_id: "note-5", limit: 5 });
    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain("q=hello");
    expect(calledUrl).toContain("note_id=note-5");
    expect(calledUrl).toContain("limit=5");
  });

  it("uses default limit of 8 when not specified", async () => {
    mockFetch.mockReturnValue(makeResponse({ items: [] }));
    await searchBlocks("http://localhost:8000", "world");
    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain("limit=8");
  });
});

// ─── fetchLocalGraph ──────────────────────────────────────────────────────────

describe("fetchLocalGraph", () => {
  const graphResponse = {
    nodes: [],
    edges: [],
    meta: {
      root_note_id: "note-1",
      applied_filters: {
        max_hops: 2,
        limit_nodes: 50,
        node_salience_threshold: 0.5,
        relationship_confidence_threshold: 0.5,
        include_types: ["note", "entity"],
      },
      truncated: false,
    },
  };

  it("builds URL with include_types as comma-joined string", async () => {
    mockFetch.mockReturnValue(makeResponse(graphResponse));
    await fetchLocalGraph("http://localhost:8000", "note-1", {
      max_hops: 2,
      limit_nodes: 50,
      node_salience_threshold: 0.5,
      relationship_confidence_threshold: 0.7,
      include_types: ["note", "entity"],
    });
    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain("include_types=note%2Centity");
    expect(calledUrl).toContain("max_hops=2");
    expect(calledUrl).toContain("limit_nodes=50");
    expect(calledUrl).toContain("node_salience_threshold=0.5");
    expect(calledUrl).toContain("relationship_confidence_threshold=0.7");
    expect(calledUrl).toContain("/v1/graph/local/note-1");
  });

  it("omits query string when no options provided", async () => {
    mockFetch.mockReturnValue(makeResponse(graphResponse));
    await fetchLocalGraph("http://localhost:8000", "note-1");
    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toBe("http://localhost:8000/v1/graph/local/note-1");
  });
});

// ─── exportNoteMarkdown ───────────────────────────────────────────────────────

describe("exportNoteMarkdown", () => {
  it("returns Blob on success", async () => {
    const blobContent = "# My Note\n\nContent here";
    mockFetch.mockReturnValue(
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
        blob: () => Promise.resolve(new Blob([blobContent], { type: "text/markdown" })),
      } as Response),
    );
    const result = await exportNoteMarkdown("http://localhost:8000", "note-1");
    expect(result).toBeInstanceOf(Blob);
    expect(result.size).toBeGreaterThan(0);
  });

  it("throws ApiClientError on 404", async () => {
    mockFetch.mockReturnValue(makeNoContentResponse(404));
    await expect(exportNoteMarkdown("http://localhost:8000", "missing")).rejects.toSatisfy(
      (err: unknown) => err instanceof ApiClientError && err.status === 404,
    );
  });
});
