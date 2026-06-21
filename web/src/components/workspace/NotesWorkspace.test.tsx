import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotesWorkspace } from "./NotesWorkspace";
import {
  ApiClientError,
  deleteNote,
  fetchCurrentUser,
  fetchLocalGraph,
  fetchNoteBacklinks,
  fetchPreferences,
  getNote,
  listNotes,
  saveNote,
} from "../../lib/api-client";

vi.mock("../../lib/api-client", () => ({
  ApiClientError: class ApiClientError extends Error {
    status: number;

    constructor(status: number) {
      super(`Request failed with status ${status}`);
      this.status = status;
    }
  },
  getBaseUrl: () => "http://localhost:8000",
  listNotes: vi.fn(),
  saveNote: vi.fn(),
  deleteNote: vi.fn(),
  getNote: vi.fn(),
  fetchNoteBacklinks: vi.fn(),
  fetchLocalGraph: vi.fn(),
  fetchCurrentUser: vi.fn().mockResolvedValue({
    id: "test-user",
    email: "test@test.com",
    display_name: "Test",
    avatar_url: null,
    oauth_provider: "dev",
    schema_name: "user_test0001",
  }),
  logoutUser: vi.fn().mockResolvedValue(undefined),
  fetchPreferences: vi.fn().mockResolvedValue({
    llm_mode: "edge",
    llm_api_key: "",
    llm_base_url: "https://api.openai.com/v1",
    llm_model: "gpt-4o-mini",
  }),
  updatePreferences: vi.fn(),
}));

vi.mock("../editor/NoteEditor", () => ({
  NoteEditor: ({
    noteId,
    onShowBacklinks,
  }: {
    noteId: string;
    onShowBacklinks?: () => void;
  }) => (
    <div data-testid="active-note-id">
      {noteId}
      {onShowBacklinks && (
        <button type="button" onClick={onShowBacklinks}>
          Linked mentions
        </button>
      )}
    </div>
  ),
}));

function noteSummary(
  noteId: string,
  overrides?: Record<string, unknown>,
): {
  note_id: string;
  note_title: string;
  subject_id: string;
  tags: string[];
  is_pinned: boolean;
  is_archived: boolean;
  content_text: string;
  updated_at: string;
  version: number;
} {
  return {
    note_id: noteId,
    note_title: `Title ${noteId}`,
    subject_id: "inbox",
    tags: [],
    is_pinned: false,
    is_archived: false,
    content_text: `Text ${noteId}`,
    updated_at: "2026-03-12T20:00:00Z",
    version: 1,
    ...overrides,
  };
}

describe("NotesWorkspace", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.localStorage.clear();
    vi.mocked(fetchCurrentUser).mockResolvedValue({
      id: "test-user",
      email: "test@test.com",
      display_name: "Test",
      avatar_url: null,
      oauth_provider: "dev",
      schema_name: "user_test0001",
    });
    vi.mocked(fetchPreferences).mockResolvedValue({
      llm_mode: "edge",
      llm_api_key: "",
      llm_base_url: "https://api.openai.com/v1",
      llm_model: "gpt-4o-mini",
      node_salience_threshold: 0.5,
      relationship_confidence_threshold: 0.5,
      llm_api_key_invalid: false,
    });
    vi.mocked(fetchLocalGraph).mockResolvedValue({
      nodes: [],
      edges: [],
      meta: {
        root_note_id: "note-a",
        applied_filters: {
          max_hops: 1,
          limit_nodes: 80,
          node_salience_threshold: 0.5, relationship_confidence_threshold: 0.5,
          include_types: ["note", "entity", "relation"],
        },
        truncated: false,
      },
    });
  });

  it("loads note list and opens the first note", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a"), noteSummary("note-b")],
      total: 2,
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    await waitFor(() => {
      expect(screen.getByTestId("active-note-id")).toHaveTextContent("note-a");
    });
  });

  it("creates a note and selects it", async () => {
    vi.mocked(listNotes)
      .mockResolvedValueOnce({
        items: [noteSummary("note-a")],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [noteSummary("note-a"), noteSummary("note-new")],
        total: 2,
      });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-new",
      saved_at: "2026-03-12T20:01:00Z",
      version: 1,
      content_hash: "hash-test",
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    await screen.findByRole("listbox", { name: "Notes" });
    fireEvent.click(screen.getByRole("button", { name: "+ New note" }));

    await waitFor(() => {
      expect(saveNote).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId("active-note-id")).toHaveTextContent("note-new");
    });
  });

  it("guards against duplicate note creation on rapid repeated clicks", async () => {
    let resolveSave!: (value: { note_id: string; saved_at: string; version: number; content_hash: string }) => void;
    const pendingSave = new Promise<{ note_id: string; saved_at: string; version: number; content_hash: string }>(
      (resolve) => {
        resolveSave = resolve;
      },
    );

    vi.mocked(listNotes)
      .mockResolvedValueOnce({
        items: [noteSummary("note-a")],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [noteSummary("note-a"), noteSummary("note-new")],
        total: 2,
      });
    vi.mocked(saveNote).mockReturnValue(pendingSave);

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const createButton = await screen.findByRole("button", { name: "+ New note" });
    fireEvent.click(createButton);
    fireEvent.click(createButton);

    expect(saveNote).toHaveBeenCalledTimes(1);
    expect(createButton).toBeDisabled();

    resolveSave({
      note_id: "note-new",
      saved_at: "2026-03-12T20:01:00Z",
      version: 1,
      content_hash: "hash-test",
    });

    await waitFor(() => {
      expect(screen.getByTestId("active-note-id")).toHaveTextContent("note-new");
    });
  });

  it("renders pinned notes separately from all notes", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        noteSummary("note-a", { note_title: "Pinned A", is_pinned: true }),
        noteSummary("note-b", { note_title: "Regular B", is_pinned: false }),
      ],
      total: 2,
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const pinnedSection = await screen.findByTestId("notes-section-pinned");
    expect(within(pinnedSection).getByRole("button", { name: /Pinned A/ })).toBeInTheDocument();

    const allSection = await screen.findByTestId("notes-section-all");
    expect(within(allSection).getByRole("button", { name: /Regular B/ })).toBeInTheDocument();
    expect(within(allSection).queryByRole("button", { name: /Pinned A/ })).not.toBeInTheDocument();
  });

  it("keeps selection and highlight in sync when selecting from recent chips", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a"), noteSummary("note-b")],
      total: 2,
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const allSection = await screen.findByTestId("notes-section-all");
    fireEvent.click(within(allSection).getByRole("button", { name: /Title note-b/ }));
    await waitFor(() => {
      expect(screen.getByTestId("active-note-id")).toHaveTextContent("note-b");
    });

    const recentSection = await screen.findByTestId("notes-section-recent");
    fireEvent.click(within(recentSection).getByRole("button", { name: "Title note-a" }));

    await waitFor(() => {
      expect(screen.getByTestId("active-note-id")).toHaveTextContent("note-a");
    });
    expect(
      within(allSection)
        .getByRole("button", { name: /Title note-a/ })
        .className,
    ).toContain("highlighted");
    expect(
      within(allSection)
        .getByRole("button", { name: /Title note-b/ })
        .className,
    ).not.toContain("highlighted");
  });

  it("opens note context menu on right click and removes top-level rename/delete actions", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Context A" })],
      total: 1,
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    expect(screen.queryByRole("button", { name: "Rename note" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete note" })).not.toBeInTheDocument();

    const allSection = await screen.findByTestId("notes-section-all");
    await waitFor(() => {
      expect(within(allSection).getByRole("button", { name: /Context A/ })).toBeInTheDocument();
    });
    const noteButton = within(allSection).getByRole("button", { name: /Context A/ });
    fireEvent.contextMenu(noteButton);

    expect(await screen.findByRole("menuitem", { name: "Rename note" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Delete note" })).toBeInTheDocument();
  });

  it("renames a note from context menu action", async () => {
    vi.mocked(listNotes)
      .mockResolvedValueOnce({
        items: [noteSummary("note-a", { note_title: "Context A" })],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [noteSummary("note-a", { note_title: "Renamed from menu" })],
        total: 1,
      });
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-a",
      note_title: "Context A",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "Text note-a",
      updated_at: "2026-03-12T20:00:00Z",
      version: 1,
      content_hash: "hash-test",
    });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-a",
      saved_at: "2026-03-12T20:01:00Z",
      version: 2,
      content_hash: "hash-test",
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const allSection = await screen.findByTestId("notes-section-all");
    await waitFor(() => {
      expect(within(allSection).getByRole("button", { name: /Context A/ })).toBeInTheDocument();
    });
    const noteButton = within(allSection).getByRole("button", { name: /Context A/ });
    fireEvent.contextMenu(noteButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename note" }));

    const renameDialog = await screen.findByRole("dialog", { name: "Rename Note" });
    const renameInput = within(renameDialog).getByRole("textbox");
    fireEvent.change(renameInput, { target: { value: "Renamed from menu" } });
    fireEvent.click(within(renameDialog).getByRole("button", { name: "OK" }));

    await waitFor(() => {
      expect(saveNote).toHaveBeenCalled();
    });
    expect(vi.mocked(saveNote).mock.calls.at(-1)?.[1]).toMatchObject({
      note_id: "note-a",
      note_title: "Renamed from menu",
    });
  });

  it("shows conflict message when rename collides with an existing title", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Context A" })],
      total: 1,
    });
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-a",
      note_title: "Context A",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "Text note-a",
      updated_at: "2026-03-12T20:00:00Z",
      version: 1,
      content_hash: "hash-test",
    });
    vi.mocked(saveNote).mockRejectedValue(new ApiClientError(409));

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const allSection = await screen.findByTestId("notes-section-all");
    await waitFor(() => {
      expect(within(allSection).getByRole("button", { name: /Context A/ })).toBeInTheDocument();
    });
    fireEvent.contextMenu(within(allSection).getByRole("button", { name: /Context A/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename note" }));

    const renameDialog = await screen.findByRole("dialog", { name: "Rename Note" });
    const renameInput = within(renameDialog).getByRole("textbox");
    fireEvent.change(renameInput, { target: { value: "Duplicate Guard" } });
    fireEvent.click(within(renameDialog).getByRole("button", { name: "OK" }));

    await waitFor(() => {
      expect(screen.getByText("A note with this title already exists")).toBeInTheDocument();
    });
  });

  it("deletes selected note from context menu action", async () => {
    vi.mocked(listNotes)
      .mockResolvedValueOnce({
        items: [noteSummary("note-a"), noteSummary("note-b")],
        total: 2,
      })
      .mockResolvedValueOnce({
        items: [noteSummary("note-b")],
        total: 1,
      });
    vi.mocked(deleteNote).mockResolvedValue();

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const allSection = await screen.findByTestId("notes-section-all");
    await waitFor(() => {
      expect(within(allSection).getByRole("button", { name: /Title note-a/ })).toBeInTheDocument();
    });
    const noteButton = within(allSection).getByRole("button", { name: /Title note-a/ });
    fireEvent.contextMenu(noteButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete note" }));

    const deleteDialog = await screen.findByRole("dialog", { name: "Delete Note" });
    fireEvent.click(within(deleteDialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(deleteNote).toHaveBeenCalledWith("http://localhost:8000", "note-a");
    });
    await waitFor(() => {
      expect(screen.getByTestId("active-note-id")).toHaveTextContent("note-b");
    });
  });

  it("refreshes list automatically after search input debounce", async () => {
    vi.mocked(listNotes)
      .mockResolvedValueOnce({
        items: [noteSummary("note-a", { note_title: "Alpha" })],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [noteSummary("note-b", { note_title: "Beta" })],
        total: 1,
      });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    await waitFor(() => {
      expect(listNotes).toHaveBeenCalledTimes(1);
    });

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "beta" } });
    await waitFor(() => {
      expect(listNotes).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(listNotes).mock.calls.at(-1)?.[1]).toMatchObject({
      search: "beta",
    });
  });

  it("renders note content preview snippet in list rows", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        noteSummary("note-a", {
          note_title: "Preview Note",
          content_text: "A long preview sentence from this note body",
        }),
      ],
      total: 1,
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    await waitFor(() => {
      expect(screen.getByText(/A long preview sentence/)).toBeInTheDocument();
    });
  });

  it("opens context menu via keyboard shortcut", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Keyboard Menu" })],
      total: 1,
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const allSection = await screen.findByTestId("notes-section-all");
    await waitFor(() => {
      expect(within(allSection).getByRole("button", { name: /Keyboard Menu/ })).toBeInTheDocument();
    });
    const noteButton = within(allSection).getByRole("button", { name: /Keyboard Menu/ });
    noteButton.focus();
    fireEvent.keyDown(noteButton, { key: "F10", shiftKey: true });

    expect(await screen.findByRole("menuitem", { name: "Rename note" })).toBeInTheDocument();
  });

  it("shows loading state while list request is pending", async () => {
    vi.mocked(listNotes).mockImplementation(
      () => new Promise(() => {}),
    );

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);
    expect(await screen.findByText("+ New note")).toBeInTheDocument();
    expect(document.querySelector(".skeleton-note-list")).toBeInTheDocument();
  });

  it("shows retry action after load failure and retries successfully", async () => {
    vi.mocked(listNotes)
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        items: [noteSummary("note-a", { note_title: "Recovered Note" })],
        total: 1,
      });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    expect(await screen.findByText("Failed to load notes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(listNotes).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      const allSection = screen.getByTestId("notes-section-all");
      expect(within(allSection).getByRole("button", { name: /Recovered Note/ })).toBeInTheDocument();
    });
  });

  it("rolls back optimistic pin toggle when persistence fails", async () => {
    let rejectSave!: (reason?: unknown) => void;
    const pendingSave = new Promise<{
      note_id: string;
      saved_at: string;
      version: number;
      content_hash: string;
    }>((_resolve, reject) => {
      rejectSave = reject;
    });

    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Pin Candidate", is_pinned: false })],
      total: 1,
    });
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-a",
      note_title: "Pin Candidate",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "Text note-a",
      updated_at: "2026-03-12T20:00:00Z",
      version: 1,
      content_hash: "hash-test",
    });
    vi.mocked(saveNote).mockReturnValue(pendingSave);

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const allSection = await screen.findByTestId("notes-section-all");
    const noteButton = within(allSection).getByRole("button", { name: /Pin Candidate/ });
    fireEvent.contextMenu(noteButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Pin note" }));

    await waitFor(() => {
      const pinnedSection = screen.getByTestId("notes-section-pinned");
      expect(within(pinnedSection).getByRole("button", { name: /Pin Candidate/ })).toBeInTheDocument();
      expect(within(allSection).queryByRole("button", { name: /Pin Candidate/ })).not.toBeInTheDocument();
    });

    rejectSave(new Error("pin failed"));

    await waitFor(() => {
      expect(screen.getByText("Failed to update pin status")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("notes-section-pinned")).not.toBeInTheDocument();
    expect(within(allSection).getByRole("button", { name: /Pin Candidate/ })).toBeInTheDocument();
  });

  it("rolls back optimistic delete when delete request fails", async () => {
    let rejectDelete!: (reason?: unknown) => void;
    const pendingDelete = new Promise<void>((_resolve, reject) => {
      rejectDelete = reject;
    });

    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Delete Candidate" })],
      total: 1,
    });
    vi.mocked(deleteNote).mockReturnValue(pendingDelete);

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);

    const allSection = await screen.findByTestId("notes-section-all");
    const noteButton = within(allSection).getByRole("button", { name: /Delete Candidate/ });
    fireEvent.contextMenu(noteButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete note" }));

    const deleteDialog = await screen.findByRole("dialog", { name: "Delete Note" });
    fireEvent.click(within(deleteDialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(within(allSection).queryByRole("button", { name: /Delete Candidate/ })).not.toBeInTheDocument();
    });

    rejectDelete(new Error("delete failed"));

    await waitFor(() => {
      expect(screen.getByText("Failed to delete note")).toBeInTheDocument();
    });
    expect(within(allSection).getByRole("button", { name: /Delete Candidate/ })).toBeInTheDocument();
  });

  it("opens quick switch with Ctrl+K and closes with Escape", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Alpha Note" })],
      total: 1,
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);
    await screen.findByTestId("notes-section-all");

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(await screen.findByRole("dialog", { name: "Quick switcher" })).toBeInTheDocument();
    expect(screen.getByLabelText("Quick switch")).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Quick switcher" })).not.toBeInTheDocument();
    });
  });

  it("opens a note from quick switch keyboard selection", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        noteSummary("note-a", { note_title: "Alpha Note" }),
        noteSummary("note-b", { note_title: "Beta Note" }),
      ],
      total: 2,
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);
    await screen.findByTestId("notes-section-all");

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByLabelText("Quick switch");
    fireEvent.change(input, { target: { value: "beta" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByTestId("active-note-id")).toHaveTextContent("note-b");
    });
  });

  it("creates a new note from quick switch action", async () => {
    vi.mocked(listNotes)
      .mockResolvedValueOnce({
        items: [noteSummary("note-a")],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [noteSummary("note-a"), noteSummary("note-new")],
        total: 2,
      });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-new",
      saved_at: "2026-03-12T20:01:00Z",
      version: 1,
      content_hash: "hash-test",
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);
    await screen.findByTestId("notes-section-all");

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByLabelText("Quick switch");
    fireEvent.change(input, { target: { value: "create" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(saveNote).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId("active-note-id")).toHaveTextContent("note-new");
    });
  });

  it("toggles pin from quick switch action", async () => {
    vi.mocked(listNotes)
      .mockResolvedValueOnce({
        items: [noteSummary("note-a", { note_title: "Pin Candidate", is_pinned: false })],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [noteSummary("note-a", { note_title: "Pin Candidate", is_pinned: true })],
        total: 1,
      });
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-a",
      note_title: "Pin Candidate",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "Text note-a",
      updated_at: "2026-03-12T20:00:00Z",
      version: 1,
      content_hash: "hash-test",
    });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-a",
      saved_at: "2026-03-12T20:01:00Z",
      version: 2,
      content_hash: "hash-test",
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);
    await screen.findByTestId("notes-section-all");

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByLabelText("Quick switch");
    fireEvent.change(input, { target: { value: "pin selected" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(saveNote).toHaveBeenCalled();
    });
    expect(vi.mocked(saveNote).mock.calls.at(-1)?.[1]).toMatchObject({
      note_id: "note-a",
      is_pinned: true,
    });
  });

  it("toggles archive from quick switch action", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Archive Candidate", is_archived: false })],
      total: 1,
    });
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-a",
      note_title: "Archive Candidate",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "Text note-a",
      updated_at: "2026-03-12T20:00:00Z",
      version: 1,
      content_hash: "hash-test",
    });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-a",
      saved_at: "2026-03-12T20:01:00Z",
      version: 2,
      content_hash: "hash-test",
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" />);
    await screen.findByTestId("notes-section-all");

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByLabelText("Quick switch");
    fireEvent.change(input, { target: { value: "archive selected" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(saveNote).toHaveBeenCalled();
    });
    expect(vi.mocked(saveNote).mock.calls.at(-1)?.[1]).toMatchObject({
      note_id: "note-a",
      is_archived: true,
    });
  });

  it("opens linked mentions modal and loads backlink items", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Target Note" })],
      total: 1,
    });
    vi.mocked(fetchNoteBacklinks).mockResolvedValue({
      note_id: "note-a",
      items: [
        {
          source_note_id: "note-b",
          source_note_title: "Source Note",
          matched_title: "Target Note",
          snippet: "Reference [[Target Note]] from source",
          updated_at: "2026-03-13T14:00:00Z",
        },
      ],
    });

    render(<NotesWorkspace baseUrl="http://localhost:8000" initialNoteId="note-a" />);
    await screen.findByTestId("active-note-id");

    fireEvent.click(screen.getByRole("button", { name: "Linked mentions" }));

    expect(await screen.findByRole("dialog", { name: "Linked mentions" })).toBeInTheDocument();
    expect(await screen.findByText(/Source Note/)).toBeInTheDocument();
    expect(fetchNoteBacklinks).toHaveBeenCalledWith("http://localhost:8000", "note-a");
  });

  it("supports escape to close linked mentions modal", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Target Note" })],
      total: 1,
    });
    vi.mocked(fetchNoteBacklinks).mockResolvedValue({ note_id: "note-a", items: [] });

    render(<NotesWorkspace baseUrl="http://localhost:8000" initialNoteId="note-a" />);
    await screen.findByTestId("active-note-id");

    fireEvent.click(screen.getByRole("button", { name: "Linked mentions" }));
    expect(await screen.findByRole("dialog", { name: "Linked mentions" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Linked mentions" })).not.toBeInTheDocument();
    });
  });

  it("shows retry when linked mentions request fails", async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [noteSummary("note-a", { note_title: "Target Note" })],
      total: 1,
    });
    vi.mocked(fetchNoteBacklinks)
      .mockRejectedValueOnce(new Error("backlink failure"))
      .mockResolvedValueOnce({ note_id: "note-a", items: [] });

    render(<NotesWorkspace baseUrl="http://localhost:8000" initialNoteId="note-a" />);
    await screen.findByTestId("active-note-id");

    fireEvent.click(screen.getByRole("button", { name: "Linked mentions" }));
    expect(await screen.findByText("Failed to load linked mentions")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(fetchNoteBacklinks).toHaveBeenCalledTimes(2);
    });
  });
});
