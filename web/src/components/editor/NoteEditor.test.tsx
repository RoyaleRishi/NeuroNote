import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NoteEditor } from "./NoteEditor";
import { ToastProvider } from "../../lib/toast";
import {
  getNote,
  queueNoteProcessing,
  saveNote,
  fetchLocalGraph,
} from "../../lib/api-client";

function renderWithProviders(ui: React.ReactElement) {
  return render(<ToastProvider>{ui}</ToastProvider>);
}

vi.mock("../../lib/api-client", () => ({
  getNote: vi.fn(),
  saveNote: vi.fn(),
  queueNoteProcessing: vi.fn(),
  fetchProcessingStatus: vi.fn(),
  fetchLocalGraph: vi.fn(),
}));

vi.mock("./TipTapEditor", () => ({
  TipTapEditor: ({
    value,
    onUpdate,
    onBlur,
    disabled,
  }: {
    value: Record<string, unknown>;
    onUpdate: (payload: { json: Record<string, unknown>; text: string }) => void;
    onBlur: () => void;
    disabled?: boolean;
  }) => {
    const firstBlock = Array.isArray(value.content) ? value.content[0] : undefined;
    const firstText =
      firstBlock &&
      typeof firstBlock === "object" &&
      Array.isArray((firstBlock as { content?: unknown[] }).content)
        ? (firstBlock as { content: unknown[] }).content[0]
        : undefined;
    const plainText =
      firstText && typeof firstText === "object" && typeof (firstText as { text?: unknown }).text === "string"
        ? (firstText as { text: string }).text
        : "";

    return (
      <textarea
        aria-label="TipTap editor"
        data-testid="tiptap-editor"
        value={plainText}
        disabled={disabled}
        onChange={(event) =>
          onUpdate({
            json: {
              type: "doc",
              content: [
                {
                  type: "paragraph",
                  content: [{ type: "text", text: event.target.value }],
                },
              ],
            },
            text: event.target.value,
          })
        }
        onBlur={onBlur}
      />
    );
  },
}));

describe("NoteEditor", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("loads existing note content into the editor", async () => {
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-1",
      note_title: "Loaded title",
      subject_id: "inbox",
      tags: ["ml"],
      is_pinned: true,
      is_archived: false,
      content_json: {
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "Loaded text" }] },
        ],
      },
      content_text: "Loaded text",
      updated_at: "2026-03-01T13:00:00Z",
      version: 1,
    });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-1",
      saved_at: "2026-03-01T13:00:01Z",
      version: 1,
    });
    vi.mocked(queueNoteProcessing).mockResolvedValue({
      job_id: "job-1",
      status: "queued",
    });

    renderWithProviders(<NoteEditor noteId="note-1" baseUrl="http://localhost:8000" />);

    await waitFor(() => {
      expect(screen.getByLabelText("TipTap editor")).toHaveValue("Loaded text");
    });
    expect(screen.getByLabelText("Note title")).toHaveValue("Loaded title");
  });

  it("marks note dirty on edit and autosaves after debounce", async () => {
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-2",
      note_title: "Initial title",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "",
      updated_at: "2026-03-01T13:01:00Z",
      version: 1,
    });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-2",
      saved_at: "2026-03-01T13:01:01Z",
      version: 2,
    });
    vi.mocked(queueNoteProcessing).mockResolvedValue({
      job_id: "job-2",
      status: "queued",
    });

    renderWithProviders(
      <NoteEditor
        noteId="note-2"
        baseUrl="http://localhost:8000"
        autosaveDebounceMs={10}
        processDebounceMs={30}
      />,
    );

    await waitFor(() =>
      expect(screen.getByLabelText("TipTap editor")).not.toBeDisabled(),
    );
    const input = screen.getByLabelText("TipTap editor");
    fireEvent.change(input, { target: { value: "Updated content" } });

    await waitFor(() => expect(saveNote).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByTestId("save-status")).toHaveTextContent("Saved"),
    );
    await waitFor(() => expect(queueNoteProcessing).toHaveBeenCalledTimes(1));
  });

  it("autosaves title updates", async () => {
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-title-1",
      note_title: "Old title",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "",
      updated_at: "2026-03-01T13:01:00Z",
      version: 1,
    });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-title-1",
      saved_at: "2026-03-01T13:01:01Z",
      version: 2,
    });
    vi.mocked(queueNoteProcessing).mockResolvedValue({
      job_id: "job-title-1",
      status: "queued",
    });

    renderWithProviders(
      <NoteEditor
        noteId="note-title-1"
        baseUrl="http://localhost:8000"
        autosaveDebounceMs={10}
        processDebounceMs={30}
      />,
    );

    await waitFor(() =>
      expect(screen.getByLabelText("Note title")).not.toBeDisabled(),
    );

    fireEvent.change(screen.getByLabelText("Note title"), {
      target: { value: "Updated title" },
    });

    await waitFor(() => expect(saveNote).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveNote).mock.calls[0]?.[1]).toMatchObject({
      note_title: "Updated title",
    });
  });

  it("surfaces save errors", async () => {
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-3",
      note_title: "Title 3",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "",
      updated_at: "2026-03-01T13:02:00Z",
      version: 1,
    });
    vi.mocked(saveNote).mockRejectedValue(new Error("save failed"));
    vi.mocked(queueNoteProcessing).mockResolvedValue({
      job_id: "job-3",
      status: "queued",
    });

    renderWithProviders(
      <NoteEditor
        noteId="note-3"
        baseUrl="http://localhost:8000"
        autosaveDebounceMs={10}
        processDebounceMs={30}
      />,
    );

    await waitFor(() =>
      expect(screen.getByLabelText("TipTap editor")).not.toBeDisabled(),
    );
    const input = screen.getByLabelText("TipTap editor");
    fireEvent.change(input, { target: { value: "Trigger error" } });

    await waitFor(() =>
      expect(screen.getByTestId("save-status")).toHaveTextContent("Save failed"),
    );
  });

  it("switches between Write and Graph tabs", async () => {
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-tab-1",
      note_title: "Tab test",
      subject_id: "inbox",
      tags: [],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "",
      updated_at: "2026-03-01T13:00:00Z",
      version: 1,
    });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-tab-1",
      saved_at: "2026-03-01T13:00:01Z",
      version: 1,
    });
    vi.mocked(fetchLocalGraph).mockResolvedValue({
      nodes: [],
      edges: [],
      meta: {
        root_note_id: "note-tab-1",
        applied_filters: { max_hops: 1, limit_nodes: 80, min_confidence: 0.35, include_types: ["note", "entity", "relation"] },
        truncated: false,
      },
    });

    renderWithProviders(<NoteEditor noteId="note-tab-1" baseUrl="http://localhost:8000" />);

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Write" })).toBeInTheDocument(),
    );

    expect(screen.getByRole("tab", { name: "Write" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Graph" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("tiptap-editor")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Graph" }));

    expect(screen.getByRole("tab", { name: "Graph" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Write" })).toHaveAttribute("aria-selected", "false");
    expect(screen.queryByTestId("tiptap-editor")).not.toBeInTheDocument();
  });

  it("autosaves organization metadata updates", async () => {
    vi.mocked(getNote).mockResolvedValue({
      note_id: "note-meta-1",
      note_title: "Meta title",
      subject_id: "inbox",
      tags: ["graph"],
      is_pinned: false,
      is_archived: false,
      content_json: { type: "doc", content: [] },
      content_text: "",
      updated_at: "2026-03-01T13:03:00Z",
      version: 1,
    });
    vi.mocked(saveNote).mockResolvedValue({
      note_id: "note-meta-1",
      saved_at: "2026-03-01T13:03:01Z",
      version: 2,
    });
    vi.mocked(queueNoteProcessing).mockResolvedValue({
      job_id: "job-meta-1",
      status: "queued",
    });

    renderWithProviders(
      <NoteEditor
        noteId="note-meta-1"
        baseUrl="http://localhost:8000"
        autosaveDebounceMs={10}
        processDebounceMs={30}
      />,
    );

    // Wait for note to load
    await screen.findByLabelText("Note title");

    // Open the options dropdown to expose the SubjectPicker
    fireEvent.click(screen.getByRole("button", { name: "Note options" }));

    // Wait for the subject badge to appear and be enabled
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "inbox" })).not.toBeDisabled(),
    );

    // Enter edit mode by clicking the subject badge, then change value
    fireEvent.click(screen.getByRole("button", { name: "inbox" }));
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "ml" },
    });
    fireEvent.change(screen.getByLabelText("Tags"), { target: { value: "graph" } });
    fireEvent.keyDown(screen.getByLabelText("Tags"), { key: "," });
    fireEvent.change(screen.getByLabelText("Tags"), { target: { value: "nlp" } });
    fireEvent.keyDown(screen.getByLabelText("Tags"), { key: "Enter" });
    fireEvent.click(screen.getByLabelText("Pinned"));

    await waitFor(() => expect(saveNote).toHaveBeenCalled());
    expect(vi.mocked(saveNote).mock.calls.at(-1)?.[1]).toMatchObject({
      subject_id: "ml",
      tags: ["graph", "nlp"],
      is_pinned: true,
    });
  });
});
