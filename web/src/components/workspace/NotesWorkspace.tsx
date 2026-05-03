"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent } from "react";

import { NoteEditor } from "../editor/NoteEditor";
import { GlobalGraphPanel } from "../graph/GlobalGraphPanel";
import { BacklinksModal } from "./BacklinksModal";
import { InputModal } from "../ui/InputModal";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { SkeletonNoteList } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { ErrorMessage } from "../ui/ErrorMessage";
import { KeyboardShortcutsModal } from "../ui/KeyboardShortcutsModal";
import { TemplateGallery } from "../templates/TemplateGallery";
import { FilterCombobox } from "../ui/FilterCombobox";
import { HelpWidget } from "../ui/HelpWidget";
import { ModelStatusIndicator } from "../llm/ModelStatusIndicator";
import { ModelDownloadProgress } from "../llm/ModelDownloadProgress";
import { WebGPUCheck } from "../llm/WebGPUCheck";
import { EdgeConsentDialog } from "../llm/EdgeConsentDialog";
import { EdgeCrashBanner } from "../llm/EdgeCrashBanner";
import { usePreferences } from "../../lib/hooks/usePreferences";
import { useEdgeLLM } from "../../lib/hooks/useEdgeLLM";
import { applyTemplate, type Template } from "../../lib/templates";
import {
  ApiClientError,
  deleteNote,
  getNote,
  importNote,
  listNotes,
  saveNote,
  updatePreferences,
} from "../../lib/api-client";
import type { WorkspaceFilters } from "../../lib/workspace/types";
import type { QuickSwitchItem } from "../../lib/workspace/quick-switch";
import type { NoteSummary } from "../../../../shared/contracts/ts/v1/note";
import { getTagColor } from "../../lib/ui/tag-colors";
import { makeNewNoteId } from "../../lib/utils/note-id";
import { useBacklinks } from "../../lib/hooks/useBacklinks";
import { useGlobalGraph } from "../../lib/hooks/useGlobalGraph";
import { useSelectionMode } from "../../lib/hooks/useSelectionMode";
import { useQuickSwitch } from "../../lib/hooks/useQuickSwitch";
import { QuickCaptureModal, type QuickCaptureResult } from "./QuickCaptureModal";
import { FileDropZone } from "./FileDropZone";
import { UserMenu } from "../auth/UserMenu";
import { useAuth } from "../../lib/hooks/useAuth";

const SELECTED_NOTE_STORAGE_KEY = "neuronote.workspace.selected";
const RECENT_NOTES_STORAGE_KEY = "neuronote.workspace.recent";
const MAX_RECENT_NOTES = 5;
const FILTER_DEBOUNCE_MS = 250;
interface NotesWorkspaceProps {
  baseUrl: string;
  initialNoteId?: string;
}

interface WorkspaceMetadataSavedPayload {
  noteId: string;
  noteTitle: string;
  subjectId: string;
  tags: string[];
  isPinned: boolean;
  isArchived: boolean;
  updatedAt: string;
  version: number;
}

interface NoteContextMenuState {
  noteId: string;
  x: number;
  y: number;
}

function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query.trim()) return text;
  const escaped = query.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(`(${escaped})`, "gi");
  const parts = text.split(regex);
  return parts.map((part, i) =>
    regex.test(part) ? (
      <mark key={i} className="search-highlight">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function compareByWorkspaceOrder(left: NoteSummary, right: NoteSummary): number {
  if (left.is_pinned !== right.is_pinned) {
    return left.is_pinned ? -1 : 1;
  }
  const updatedDiff = right.updated_at.localeCompare(left.updated_at);
  if (updatedDiff !== 0) {
    return updatedDiff;
  }
  return left.note_id.localeCompare(right.note_id);
}

function sortWorkspaceNotes(items: NoteSummary[]): NoteSummary[] {
  return [...items].sort(compareByWorkspaceOrder);
}

function pickFallbackSelection(items: NoteSummary[]): string | null {
  return sortWorkspaceNotes(items)[0]?.note_id ?? null;
}

function loadRecentNotes(): string[] {
  const raw = window.localStorage.getItem(RECENT_NOTES_STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item): item is string => typeof item === "string");
  } catch {
    return [];
  }
}

function persistRecentNotes(noteIds: string[]): void {
  window.localStorage.setItem(
    RECENT_NOTES_STORAGE_KEY,
    JSON.stringify(noteIds.slice(0, MAX_RECENT_NOTES)),
  );
}

function toPreview(content: string): string {
  const normalized = content.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "No content yet";
  }
  if (normalized.length <= 96) {
    return normalized;
  }
  return `${normalized.slice(0, 93)}...`;
}

function toDisplayDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Unknown";
  }
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function NewNoteButton({
  disabled,
  onCreate,
  onTemplate,
}: {
  disabled: boolean;
  onCreate: () => void;
  onTemplate: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [open]);

  return (
    <div ref={ref} className="new-note-split">
      <button
        type="button"
        className="btn btn-primary btn-sm new-note-split-main"
        onClick={onCreate}
        disabled={disabled}
      >
        + New note
      </button>
      <button
        type="button"
        className="btn btn-primary btn-sm new-note-split-arrow"
        onClick={() => setOpen((prev) => !prev)}
        disabled={disabled}
        aria-label="More create options"
        aria-expanded={open}
      >
        ▾
      </button>
      {open && (
        <div className="new-note-split-dropdown">
          <button
            type="button"
            className="new-note-split-option"
            onClick={() => { onTemplate(); setOpen(false); }}
          >
            From template
          </button>
        </div>
      )}
    </div>
  );
}

export function NotesWorkspace({ baseUrl, initialNoteId }: NotesWorkspaceProps) {
  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(initialNoteId ?? null);
  const [highlightedNoteId, setHighlightedNoteId] = useState<string | null>(initialNoteId ?? null);
  const [recentNoteIds, setRecentNoteIds] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [subjectFilter, setSubjectFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreatingNote, setIsCreatingNote] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<NoteContextMenuState | null>(null);
  const [appView, setAppView] = useState<"notes" | "graph">("notes");
  const [renameModalOpen, setRenameModalOpen] = useState(false);
  const [noteToRename, setNoteToRename] = useState<NoteSummary | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [noteToDelete, setNoteToDelete] = useState<NoteSummary | null>(null);
  const [shortcutsModalOpen, setShortcutsModalOpen] = useState(false);
  const [templateGalleryOpen, setTemplateGalleryOpen] = useState(false);
  const [quickCaptureOpen, setQuickCaptureOpen] = useState(false);
  const createInFlightRef = useRef(false);
  const contextMenuRef = useRef<HTMLUListElement | null>(null);
  const filtersInitializedRef = useRef(false);

  // ── Auth ──
  const { user } = useAuth();

  // ── Preferences ──
  const { prefs, reload: reloadPrefs } = usePreferences();

  // ── Edge LLM lifecycle ──
  // Bumping `edgeRetryToken` re-runs WebGPU detection + engine init
  // (driven by the WebGPU unsupported modal's "Try Again" button).
  const [edgeRetryToken, setEdgeRetryToken] = useState(0);
  const edgeMode = prefs?.llm_mode === "edge";
  const edge = useEdgeLLM(edgeMode, edgeRetryToken);

  const switchToCloud = useCallback(async () => {
    try {
      await updatePreferences({ llm_mode: "cloud" });
      void reloadPrefs();
    } catch (err) {
      console.error("[NotesWorkspace] switchToCloud failed", err);
    }
  }, [reloadPrefs]);

  // ── Extracted hooks ──
  const qs = useQuickSwitch(notes, selectedNoteId);
  const backlinks = useBacklinks(baseUrl);
  const globalGraph = useGlobalGraph(baseUrl, prefs?.confidence_threshold ?? 0.9);
  const selection = useSelectionMode();

  const filters: WorkspaceFilters = useMemo(
    () => ({
      search,
      subjectId: subjectFilter,
      tag: tagFilter,
      showArchived,
    }),
    [search, showArchived, subjectFilter, tagFilter],
  );

  const availableSubjects = useMemo(() => {
    const seen = new Set<string>();
    for (const note of notes) {
      if (note.subject_id) seen.add(note.subject_id);
    }
    return Array.from(seen).sort();
  }, [notes]);

  const availableTags = useMemo(() => {
    const seen = new Set<string>();
    for (const note of notes) {
      for (const tag of note.tags) {
        if (tag) seen.add(tag);
      }
    }
    return Array.from(seen).sort();
  }, [notes]);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  const openContextMenu = useCallback(
    (noteId: string, x: number, y: number) => {
      setSelectedNoteId(noteId);
      setContextMenu({
        noteId,
        x: x + 8,
        y: y + 8,
      });
    },
    [],
  );

  const refreshNotes = useCallback(
    async (preferredNoteId?: string | null) => {
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const response = await listNotes(baseUrl, {
          limit: 100,
          offset: 0,
          search: filters.search.trim() || undefined,
          subject_id: filters.subjectId.trim() || undefined,
          tag: filters.tag.trim() || undefined,
          is_archived: filters.showArchived,
        });
        setNotes(sortWorkspaceNotes(response.items));

        setSelectedNoteId((current) => {
          const persisted = window.localStorage.getItem(SELECTED_NOTE_STORAGE_KEY);
          const candidateIds = [preferredNoteId, current, initialNoteId, persisted];
          for (const candidate of candidateIds) {
            if (!candidate) {
              continue;
            }
            if (response.items.some((note) => note.note_id === candidate)) {
              return candidate;
            }
          }
          return pickFallbackSelection(response.items);
        });
      } catch {
        setErrorMessage("Failed to load notes");
        setNotes([]);
        setSelectedNoteId(null);
      } finally {
        setIsLoading(false);
      }
    },
    [baseUrl, filters, initialNoteId],
  );

  useEffect(() => {
    setRecentNoteIds(loadRecentNotes());
    void refreshNotes(initialNoteId ?? null);
  }, [initialNoteId, refreshNotes]);

  useEffect(() => {
    if (!filtersInitializedRef.current) {
      filtersInitializedRef.current = true;
      return;
    }
    const timer = window.setTimeout(() => {
      void refreshNotes(null);
    }, FILTER_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [refreshNotes, search, showArchived, subjectFilter, tagFilter]);

  useEffect(() => {
    if (!selectedNoteId) {
      return;
    }
    window.localStorage.setItem(SELECTED_NOTE_STORAGE_KEY, selectedNoteId);
    setRecentNoteIds((current) => {
      const next = [selectedNoteId, ...current.filter((item) => item !== selectedNoteId)];
      persistRecentNotes(next);
      return next.slice(0, MAX_RECENT_NOTES);
    });
  }, [selectedNoteId]);

  useEffect(() => {
    if (appView === "graph") {
      void globalGraph.load();
    }
  }, [appView, globalGraph.load]);

  useEffect(() => {
    if (selectedNoteId && notes.some((note) => note.note_id === selectedNoteId)) {
      setHighlightedNoteId(selectedNoteId);
      return;
    }
    const firstUnpinned = notes.find((note) => !note.is_pinned);
    const fallback = firstUnpinned ?? notes[0] ?? null;
    setHighlightedNoteId(fallback?.note_id ?? null);
  }, [notes, selectedNoteId]);

  useEffect(() => {
    if (!contextMenu) {
      return;
    }

    const handleMouseDown = (event: MouseEvent) => {
      if (!contextMenuRef.current) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (!contextMenuRef.current.contains(target)) {
        closeContextMenu();
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeContextMenu();
      }
    };

    window.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [closeContextMenu, contextMenu]);

  const recentNotes = useMemo(() => {
    const index = new Map(notes.map((note) => [note.note_id, note]));
    return recentNoteIds.map((noteId) => index.get(noteId)).filter((item): item is NoteSummary => Boolean(item));
  }, [notes, recentNoteIds]);
  const pinnedNotes = useMemo(() => notes.filter((note) => note.is_pinned), [notes]);
  const unpinnedNotes = useMemo(() => notes.filter((note) => !note.is_pinned), [notes]);
  const contextNote = useMemo(
    () => (contextMenu ? notes.find((item) => item.note_id === contextMenu.noteId) ?? null : null),
    [contextMenu, notes],
  );
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const isQuickSwitchShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
      if (isQuickSwitchShortcut) {
        event.preventDefault();
        closeContextMenu();
        qs.open();
        return;
      }
      const isQuickCaptureShortcut = (event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "n";
      if (isQuickCaptureShortcut) {
        event.preventDefault();
        setQuickCaptureOpen(true);
        return;
      }
      if (event.key === "?" && !event.metaKey && !event.ctrlKey && !event.altKey) {
        const tag = (event.target as HTMLElement)?.tagName;
        if (tag !== "INPUT" && tag !== "TEXTAREA") {
          event.preventDefault();
          setShortcutsModalOpen(true);
          return;
        }
      }
      if (!qs.isOpen) {
        if (backlinks.isOpen && event.key === "Escape") {
          event.preventDefault();
          backlinks.close();
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        qs.close();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [backlinks.isOpen, backlinks.close, closeContextMenu, qs.isOpen, qs.open, qs.close]);

  const handleMetadataSaved = useCallback(
    async (payload: WorkspaceMetadataSavedPayload) => {
      setNotes((current) =>
        sortWorkspaceNotes(
          current.map((item) =>
            item.note_id === payload.noteId
              ? {
                  ...item,
                  note_title: payload.noteTitle,
                  subject_id: payload.subjectId,
                  tags: payload.tags,
                  is_pinned: payload.isPinned,
                  is_archived: payload.isArchived,
                  updated_at: payload.updatedAt,
                  version: payload.version,
                }
              : item,
          ),
        ),
      );
      await refreshNotes(payload.noteId);
    },
    [refreshNotes],
  );

  const handleCreateNote = useCallback(async () => {
    if (createInFlightRef.current) {
      return;
    }
    createInFlightRef.current = true;
    setIsCreatingNote(true);
    const newNoteId = makeNewNoteId();
    try {
      const created = await saveNote(baseUrl, {
        note_id: newNoteId,
        note_title: "Untitled",
        subject_id: "inbox",
        tags: [],
        is_pinned: false,
        is_archived: false,
        content_json: { type: "doc", content: [] },
        content_text: " ",
        updated_at: new Date().toISOString(),
      });
      await refreshNotes(created.note_id);
    } catch {
      setErrorMessage("Failed to create note");
    } finally {
      createInFlightRef.current = false;
      setIsCreatingNote(false);
    }
  }, [baseUrl, refreshNotes]);

  const handleCreateNoteFromTemplate = useCallback(
    async (template: Template) => {
      if (template.category === "blank") {
        await handleCreateNote();
        return;
      }
      if (createInFlightRef.current) {
        return;
      }
      createInFlightRef.current = true;
      setIsCreatingNote(true);
      const newNoteId = makeNewNoteId();
      const vars: Record<string, string> = {
        title: template.name,
        date: new Date().toISOString().split("T")[0] ?? "",
      };
      const content = applyTemplate(template, vars);
      try {
        const created = await saveNote(baseUrl, {
          note_id: newNoteId,
          note_title: template.name,
          subject_id: "inbox",
          tags: [],
          is_pinned: false,
          is_archived: false,
          content_json: { type: "doc", content: [] },
          content_text: content,
          updated_at: new Date().toISOString(),
        });
        await refreshNotes(created.note_id);
      } catch {
        setErrorMessage("Failed to create note from template");
      } finally {
        createInFlightRef.current = false;
        setIsCreatingNote(false);
      }
    },
    [baseUrl, refreshNotes, handleCreateNote],
  );

  const handleQuickCaptureSave = useCallback(
    async (result: QuickCaptureResult) => {
      const newNoteId = makeNewNoteId();
      const paragraphs = result.body
        ? result.body.split("\n").map((line) => ({
            type: "paragraph" as const,
            content: line ? [{ type: "text" as const, text: line }] : [],
          }))
        : [];
      try {
        const created = await saveNote(baseUrl, {
          note_id: newNoteId,
          note_title: result.title,
          subject_id: "inbox",
          tags: [],
          is_pinned: false,
          is_archived: false,
          content_json: { type: "doc", content: paragraphs },
          content_text: result.body || " ",
          updated_at: new Date().toISOString(),
        });
        await refreshNotes(created.note_id);
      } catch {
        setErrorMessage("Failed to create note from quick capture");
      }
    },
    [baseUrl, refreshNotes],
  );

  const handleFileImport = useCallback(
    async (filename: string, content: string) => {
      try {
        const result = await importNote(baseUrl, { filename, content });
        await refreshNotes(result.note_id);
      } catch {
        setErrorMessage("Failed to import file");
      }
    },
    [baseUrl, refreshNotes],
  );

  const handleRenameNote = useCallback(
    (noteId: string) => {
      const selected = notes.find((item) => item.note_id === noteId);
      if (!selected) {
        return;
      }
      setNoteToRename(selected);
      setRenameModalOpen(true);
      closeContextMenu();
    },
    [notes, closeContextMenu],
  );

  const handleRenameSubmit = useCallback(
    async (nextTitle: string) => {
      if (!noteToRename) return;

      const trimmedTitle = nextTitle.trim();
      if (!trimmedTitle || trimmedTitle === noteToRename.note_title) {
        return;
      }

      const previousNotes = notes;
      setNotes((current) =>
        sortWorkspaceNotes(
          current.map((item) =>
            item.note_id === noteToRename.note_id
              ? {
                  ...item,
                  note_title: trimmedTitle,
                  updated_at: new Date().toISOString(),
                }
              : item,
          ),
        ),
      );

      try {
        const existing = await getNote(baseUrl, noteToRename.note_id);
        await saveNote(baseUrl, {
          note_id: existing.note_id,
          note_title: trimmedTitle,
          subject_id: existing.subject_id,
          tags: existing.tags,
          is_pinned: existing.is_pinned,
          is_archived: existing.is_archived,
          content_json: existing.content_json,
          content_text: existing.content_text,
          updated_at: new Date().toISOString(),
        });
        await refreshNotes(noteToRename.note_id);
      } catch (error) {
        setNotes(previousNotes);
        if (error instanceof ApiClientError && error.status === 409) {
          setErrorMessage("A note with this title already exists");
          return;
        }
        setErrorMessage("Failed to rename note");
      }
    },
    [baseUrl, notes, noteToRename, refreshNotes],
  );

  const handleDeleteClick = useCallback(
    (noteId: string) => {
      const note = notes.find((item) => item.note_id === noteId);
      if (!note) return;
      setNoteToDelete(note);
      setDeleteDialogOpen(true);
      closeContextMenu();
    },
    [notes, closeContextMenu],
  );

  const handleDeleteConfirm = useCallback(
    async () => {
      if (!noteToDelete) return;

      const noteId = noteToDelete.note_id;
      const previousNotes = notes;
      const previousSelected = selectedNoteId;
      const remaining = notes.filter((item) => item.note_id !== noteId);

      setNotes(sortWorkspaceNotes(remaining));
      setSelectedNoteId((current) => {
        if (current !== noteId) {
          return current;
        }
        return pickFallbackSelection(remaining);
      });
      setHighlightedNoteId((current) => {
        if (current !== noteId) {
          return current;
        }
        return pickFallbackSelection(remaining);
      });

      try {
        await deleteNote(baseUrl, noteId);
        await refreshNotes(null);
      } catch {
        setNotes(previousNotes);
        setSelectedNoteId(previousSelected);
        setHighlightedNoteId(previousSelected ?? pickFallbackSelection(previousNotes));
        setErrorMessage("Failed to delete note");
      }
    },
    [baseUrl, notes, noteToDelete, refreshNotes, selectedNoteId],
  );

  const handleBulkDelete = useCallback(async () => {
    if (selection.selectedNoteIds.size === 0) return;
    for (const noteId of selection.selectedNoteIds) {
      try {
        await deleteNote(baseUrl, noteId);
      } catch {
        // continue deleting others even if one fails
      }
    }
    selection.clearSelection();
    void refreshNotes(selectedNoteId);
  }, [baseUrl, selection.clearSelection, refreshNotes, selectedNoteId, selection.selectedNoteIds]);

  const handleBulkTag = useCallback(async (tagValue: string) => {
    if (selection.selectedNoteIds.size === 0) return;
    for (const noteId of selection.selectedNoteIds) {
      try {
        const existing = await getNote(baseUrl, noteId);
        const updatedTags = Array.from(new Set([...existing.tags, tagValue.trim().toLowerCase()]));
        await saveNote(baseUrl, {
          note_id: existing.note_id,
          note_title: existing.note_title,
          subject_id: existing.subject_id,
          tags: updatedTags,
          is_pinned: existing.is_pinned,
          is_archived: existing.is_archived,
          content_json: existing.content_json,
          content_text: existing.content_text,
          updated_at: new Date().toISOString(),
        });
      } catch {
        // continue
      }
    }
    selection.clearSelection();
    void refreshNotes(selectedNoteId);
  }, [baseUrl, selection.clearSelection, refreshNotes, selectedNoteId, selection.selectedNoteIds]);

  const handleBulkSubject = useCallback(async (subjectValue: string) => {
    if (selection.selectedNoteIds.size === 0) return;
    for (const noteId of selection.selectedNoteIds) {
      try {
        const existing = await getNote(baseUrl, noteId);
        await saveNote(baseUrl, {
          note_id: existing.note_id,
          note_title: existing.note_title,
          subject_id: subjectValue.trim(),
          tags: existing.tags,
          is_pinned: existing.is_pinned,
          is_archived: existing.is_archived,
          content_json: existing.content_json,
          content_text: existing.content_text,
          updated_at: new Date().toISOString(),
        });
      } catch {
        // continue
      }
    }
    selection.clearSelection();
    void refreshNotes(selectedNoteId);
  }, [baseUrl, selection.clearSelection, refreshNotes, selectedNoteId, selection.selectedNoteIds]);

  const handleTogglePinnedNote = useCallback(
    async (noteId: string) => {
      const target = notes.find((item) => item.note_id === noteId);
      if (!target) {
        closeContextMenu();
        return;
      }
      const previousNotes = notes;

      setNotes((current) =>
        sortWorkspaceNotes(
          current.map((item) =>
            item.note_id === noteId
              ? {
                  ...item,
                  is_pinned: !item.is_pinned,
                  updated_at: new Date().toISOString(),
                }
              : item,
          ),
        ),
      );
      closeContextMenu();

      try {
        const existing = await getNote(baseUrl, noteId);
        await saveNote(baseUrl, {
          note_id: existing.note_id,
          note_title: existing.note_title,
          subject_id: existing.subject_id,
          tags: existing.tags,
          is_pinned: !existing.is_pinned,
          is_archived: existing.is_archived,
          content_json: existing.content_json,
          content_text: existing.content_text,
          updated_at: new Date().toISOString(),
        });
        await refreshNotes(noteId);
      } catch {
        setNotes(previousNotes);
        setErrorMessage("Failed to update pin status");
      }
    },
    [baseUrl, closeContextMenu, notes, refreshNotes],
  );

  const handleToggleArchivedNote = useCallback(
    async (noteId: string) => {
      const target = notes.find((item) => item.note_id === noteId);
      if (!target) {
        closeContextMenu();
        return;
      }
      const nextArchivedState = !target.is_archived;
      const previousNotes = notes;
      const previousSelected = selectedNoteId;

      const optimisticNotes = sortWorkspaceNotes(
        notes
          .map((item) =>
            item.note_id === noteId
              ? {
                  ...item,
                  is_archived: nextArchivedState,
                  updated_at: new Date().toISOString(),
                }
              : item,
          )
          .filter((item) => showArchived || !item.is_archived),
      );
      setNotes(optimisticNotes);

      if (nextArchivedState && !showArchived && selectedNoteId === noteId) {
        const fallback = pickFallbackSelection(optimisticNotes);
        setSelectedNoteId(fallback);
        setHighlightedNoteId(fallback);
      }
      closeContextMenu();

      try {
        const existing = await getNote(baseUrl, noteId);
        await saveNote(baseUrl, {
          note_id: existing.note_id,
          note_title: existing.note_title,
          subject_id: existing.subject_id,
          tags: existing.tags,
          is_pinned: existing.is_pinned,
          is_archived: nextArchivedState,
          content_json: existing.content_json,
          content_text: existing.content_text,
          updated_at: new Date().toISOString(),
        });
        await refreshNotes(nextArchivedState && !showArchived ? null : noteId);
      } catch {
        setNotes(previousNotes);
        setSelectedNoteId(previousSelected);
        setHighlightedNoteId(previousSelected ?? pickFallbackSelection(previousNotes));
        setErrorMessage("Failed to update archive status");
      }
    },
    [baseUrl, closeContextMenu, notes, refreshNotes, selectedNoteId, showArchived],
  );

  const executeQuickSwitchItem = useCallback(
    async (item: QuickSwitchItem) => {
      qs.close();
      if (item.actionId === "open_note") {
        if (!item.noteId) {
          return;
        }
        setSelectedNoteId(item.noteId);
        setHighlightedNoteId(item.noteId);
        return;
      }
      if (item.actionId === "create_note") {
        await handleCreateNote();
        return;
      }

      const targetNoteId = item.noteId ?? selectedNoteId;
      if (!targetNoteId) {
        return;
      }
      if (item.actionId === "toggle_pin_selected") {
        await handleTogglePinnedNote(targetNoteId);
        return;
      }
      if (item.actionId === "toggle_archive_selected") {
        await handleToggleArchivedNote(targetNoteId);
        return;
      }
      if (item.actionId === "show_backlinks") {
        selectedNoteId && backlinks.open(selectedNoteId);
        return;
      }
      if (item.actionId === "view_global_graph") {
        setAppView("graph");
      }
    },
    [
      qs.close,
      handleCreateNote,
      handleToggleArchivedNote,
      handleTogglePinnedNote,
      backlinks,
      selectedNoteId,
      setAppView,
    ],
  );

  const handleQuickSwitchKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLInputElement>) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        qs.moveSelection(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        qs.moveSelection(-1);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const target = qs.filteredItems[qs.selectedIndex] ?? qs.filteredItems[0];
        if (target) {
          void executeQuickSwitchItem(target);
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        qs.close();
      }
    },
    [qs.close, executeQuickSwitchItem, qs.filteredItems, qs.selectedIndex],
  );

  const handleListKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLUListElement>) => {
      if (!unpinnedNotes.length) {
        return;
      }
      const activeIndex = unpinnedNotes.findIndex((note) => note.note_id === highlightedNoteId);
      const safeIndex = activeIndex >= 0 ? activeIndex : 0;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        const nextIndex = Math.min(safeIndex + 1, unpinnedNotes.length - 1);
        setHighlightedNoteId(unpinnedNotes[nextIndex]?.note_id ?? null);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        const nextIndex = Math.max(safeIndex - 1, 0);
        setHighlightedNoteId(unpinnedNotes[nextIndex]?.note_id ?? null);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const target = unpinnedNotes[safeIndex];
        if (target) {
          setSelectedNoteId(target.note_id);
        }
      }
    },
    [highlightedNoteId, unpinnedNotes],
  );

  const handleNoteContextMenu = useCallback(
    (event: ReactMouseEvent<HTMLButtonElement>, noteId: string) => {
      event.preventDefault();
      openContextMenu(noteId, event.clientX, event.clientY);
    },
    [openContextMenu],
  );

  const handleNoteContextMenuKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>, noteId: string) => {
      if ((event.shiftKey && event.key === "F10") || event.key === "ContextMenu") {
        event.preventDefault();
        const rect = event.currentTarget.getBoundingClientRect();
        openContextMenu(noteId, rect.left + 8, rect.bottom + 8);
      }
    },
    [openContextMenu],
  );

  const renderNoteButton = useCallback(
    (note: NoteSummary, highlighted = false) => (
      <button
        type="button"
        className={`note-list-button${note.note_id === selectedNoteId ? " selected" : ""}${highlighted ? " highlighted" : ""}`}
        onClick={() => {
          setSelectedNoteId(note.note_id);
          setHighlightedNoteId(note.note_id);
          closeContextMenu();
        }}
        onContextMenu={(event) => handleNoteContextMenu(event, note.note_id)}
        onKeyDown={(event) => handleNoteContextMenuKeyDown(event, note.note_id)}
        aria-haspopup="menu"
      >
        <span className="note-list-title">{highlightMatch(note.note_title, search)}</span>
        <span className="note-list-preview">{highlightMatch(toPreview(note.content_text), search)}</span>
        <div className="note-list-tags-row">
          {note.subject_id && note.subject_id !== "inbox" && (
            <span className="note-list-subject-badge">{note.subject_id}</span>
          )}
          {note.tags.slice(0, 3).map((tag) => {
            const c = getTagColor(tag);
            return (
              <span key={tag} className="note-list-tag-chip"
                style={{ backgroundColor: c.bg, color: c.text }}>
                {tag}
              </span>
            );
          })}
          <span className="note-list-date">{toDisplayDate(note.updated_at)}</span>
        </div>
      </button>
    ),
    [closeContextMenu, handleNoteContextMenu, handleNoteContextMenuKeyDown, search, selectedNoteId],
  );

  return (
    <div className="app-shell">
      <EdgeCrashBanner
        isOpen={edgeMode && edge.status === "awaiting-recovery"}
        onAcknowledge={(action) => {
          edge.acknowledgeRecovery(action);
          if (action === "switchToCloud") {
            void switchToCloud();
          }
        }}
      />
      <ModelDownloadProgress status={edge.status} progress={edge.progress} />
      <nav className="app-nav">
        <span className="app-nav-brand">NeuroNote</span>
        <div className="app-nav-tabs" role="tablist" aria-label="App view">
          <button
            type="button"
            role="tab"
            className={`app-nav-tab${appView === "notes" ? " active" : ""}`}
            aria-selected={appView === "notes"}
            onClick={() => setAppView("notes")}
          >
            Notes
          </button>
          <button
            type="button"
            role="tab"
            className={`app-nav-tab${appView === "graph" ? " active" : ""}`}
            aria-selected={appView === "graph"}
            onClick={() => setAppView("graph")}
          >
            Graph
          </button>
        </div>
        <ModelStatusIndicator
          mode={prefs?.llm_mode}
          status={edge.status}
          progress={edge.progress}
          error={edge.error}
        />
        <UserMenu user={user} />
      </nav>

      <EdgeConsentDialog
        isOpen={edgeMode && edge.status === "awaiting-consent"}
        onAccept={edge.acceptConsent}
        onDecline={() => {
          edge.declineConsent();
          void switchToCloud();
        }}
        onDismiss={() => {
          // Leave consent absent; the dialog re-shows on reload.
          // No state change needed because the hook's status remains
          // 'awaiting-consent' until the user makes a choice.
        }}
      />

      {/* WebGPU support check — shown when edge mode is selected but unsupported */}
      <WebGPUCheck
        isOpen={edgeMode && edge.status === "unsupported"}
        onOpenSettings={() => { void switchToCloud(); }}
        onRetry={() => setEdgeRetryToken((n) => n + 1)}
      />

      {appView === "graph" ? (
        <GlobalGraphPanel
          baseUrl={baseUrl}
          graph={globalGraph.graph}
          filters={globalGraph.filters}
          isLoading={globalGraph.isLoading}
          errorMessage={globalGraph.errorMessage}
          availableSubjects={availableSubjects}
          availableTags={availableTags}
          onRetry={() => { void globalGraph.load(); }}
          onFiltersChange={(next) => { globalGraph.setFilters(next); }}
          onOpenNote={(nextNoteId) => {
            if (!notes.some((item) => item.note_id === nextNoteId)) return;
            setAppView("notes");
            setSelectedNoteId(nextNoteId);
            setHighlightedNoteId(nextNoteId);
          }}
        />
      ) : (
      <FileDropZone onFileContent={(name, content) => void handleFileImport(name, content)}>
      <section className="notes-workspace" data-testid="notes-workspace">
      <aside className="notes-sidebar">
        <header className="notes-sidebar-header">
          <h1>Notes</h1>
          <div className="notes-sidebar-actions">
            <button
              type="button"
              className={`editor-command-button${selection.selectionMode ? " active" : ""}`}
              onClick={() => {
                if (selection.selectionMode) {
                  selection.clearSelection();
                } else {
                  selection.setSelectionMode(true);
                }
              }}
            >
              {selection.selectionMode ? "Cancel" : "Select"}
            </button>
            <NewNoteButton
              disabled={isCreatingNote}
              onCreate={() => void handleCreateNote()}
              onTemplate={() => setTemplateGalleryOpen(true)}
            />
          </div>
        </header>

        {selection.selectionMode && (
          <div className="bulk-actions-bar">
            <span className="bulk-actions-count">{selection.selectedNoteIds.size} selected</span>
            <div className="bulk-actions-buttons">
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => selection.selectAll(notes.map((n) => n.note_id))}>All</button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => selection.setBulkTagDialogOpen(true)} disabled={selection.selectedNoteIds.size === 0}>Tag</button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => selection.setBulkSubjectDialogOpen(true)} disabled={selection.selectedNoteIds.size === 0}>Subject</button>
              <button type="button" className="btn btn-sm btn-danger" onClick={() => selection.setBulkDeleteDialogOpen(true)} disabled={selection.selectedNoteIds.size === 0}>Delete</button>
            </div>
          </div>
        )}

        <div className="workspace-stat-grid" aria-label="Workspace summary">
          <article className="workspace-stat-card">
            <span className="workspace-stat-label">Total</span>
            <strong className="workspace-stat-value">{notes.length}</strong>
          </article>
          <article className="workspace-stat-card">
            <span className="workspace-stat-label">Pinned</span>
            <strong className="workspace-stat-value">{pinnedNotes.length}</strong>
          </article>
          <article className="workspace-stat-card">
            <span className="workspace-stat-label">Recent</span>
            <strong className="workspace-stat-value">{recentNotes.length}</strong>
          </article>
        </div>

        <div className="notes-filters">
          <label className="notes-filter-label">
            Search
            <input
              aria-label="Search"
              className="notes-filter-input"
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <FilterCombobox
            label="Subject"
            value={subjectFilter}
            onChange={setSubjectFilter}
            options={availableSubjects}
          />
          <FilterCombobox
            label="Tag"
            value={tagFilter}
            onChange={setTagFilter}
            options={availableTags}
          />
          <label className="notes-toggle-filter">
            <input
              aria-label="Show archived"
              type="checkbox"
              checked={showArchived}
              onChange={(event) => {
                setShowArchived(event.target.checked);
              }}
            />
            Show archived
          </label>
        </div>

        {recentNotes.length > 0 ? (
          <section className="notes-section" data-testid="notes-section-recent">
            <h2>
              Recent
              <span>{recentNotes.length}</span>
            </h2>
            <div className="notes-chip-list">
              {recentNotes.map((note) => (
                <button
                  key={`recent-${note.note_id}`}
                  type="button"
                  className={`notes-chip${note.note_id === selectedNoteId ? " selected" : ""}`}
                  onClick={() => {
                    setSelectedNoteId(note.note_id);
                    setHighlightedNoteId(note.note_id);
                    closeContextMenu();
                  }}
                >
                  {note.note_title}
                </button>
              ))}
            </div>
          </section>
        ) : null}

        {pinnedNotes.length > 0 ? (
          <section className="notes-section" data-testid="notes-section-pinned">
            <h2>
              Pinned
              <span>{pinnedNotes.length}</span>
            </h2>
            <ul className="notes-list">
              {pinnedNotes.map((note) => (
                <li key={`pinned-${note.note_id}`}>
                  {selection.selectionMode && (
                    <label className="note-select-checkbox">
                      <input
                        type="checkbox"
                        checked={selection.selectedNoteIds.has(note.note_id)}
                        onChange={() => selection.toggleSelection(note.note_id)}
                        aria-label={`Select ${note.note_title}`}
                      />
                    </label>
                  )}
                  {renderNoteButton(note)}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="notes-section" data-testid="notes-section-all">
          <h2>
            All notes
            <span>{unpinnedNotes.length}</span>
          </h2>
          <ul
            className="notes-list"
            role="listbox"
            aria-label="Notes"
            tabIndex={0}
            onKeyDown={handleListKeyDown}
          >
            {unpinnedNotes.map((note) => (
              <li
                key={note.note_id}
                role="option"
                aria-selected={note.note_id === selectedNoteId}
              >
                {selection.selectionMode && (
                  <label className="note-select-checkbox">
                    <input
                      type="checkbox"
                      checked={selection.selectedNoteIds.has(note.note_id)}
                      onChange={() => selection.toggleSelection(note.note_id)}
                      aria-label={`Select ${note.note_title}`}
                    />
                  </label>
                )}
                {renderNoteButton(note, note.note_id === highlightedNoteId)}
              </li>
            ))}
          </ul>
          {!isLoading && unpinnedNotes.length === 0 && notes.length > 0 ? (
            <p className="notes-empty-minor">All notes are pinned.</p>
          ) : null}
        </section>

        {isLoading ? <SkeletonNoteList count={8} /> : null}
        {!isLoading && notes.length === 0 ? (
          <EmptyState
            icon="📝"
            title="No notes yet"
            description="Create your first note to get started building your knowledge graph."
            actionLabel="Create note"
            onAction={() => void handleCreateNote()}
          />
        ) : null}
        {errorMessage ? (
          <ErrorMessage
            message={errorMessage}
            actionLabel="Retry"
            onAction={() => void refreshNotes(selectedNoteId)}
          />
        ) : null}
      </aside>

      <main className="notes-editor-panel">
        <div className="notes-editor-actions">
          <button
            type="button"
            className="editor-command-button"
            ref={backlinks.triggerRef as React.RefObject<HTMLButtonElement>}
            onClick={() => selectedNoteId && backlinks.open(selectedNoteId)}
            disabled={!selectedNoteId}
          >
            Linked mentions
          </button>
        </div>
        {selectedNoteId ? (
          <NoteEditor
            key={selectedNoteId}
            noteId={selectedNoteId}
            baseUrl={baseUrl}
            onMetadataSaved={(payload) => {
              void handleMetadataSaved(payload);
            }}
            availableSubjects={availableSubjects}
            availableTags={availableTags}
            onOpenNote={(nextNoteId) => {
              if (!notes.some((item) => item.note_id === nextNoteId)) return;
              setSelectedNoteId(nextNoteId);
              setHighlightedNoteId(nextNoteId);
            }}
            llmMode={prefs?.llm_mode}
            confidenceThreshold={prefs?.confidence_threshold ?? 0.9}
            edgeReady={edge.isReady}
            edgeMarkStableInference={edge.markStableInference}
          />
        ) : (
          <div className="notes-empty-state">
            <h2>No note selected</h2>
            <p>Select or create a note to begin editing.</p>
          </div>
        )}
      </main>

      </section>
      </FileDropZone>
      )}

      <BacklinksModal
        isOpen={backlinks.isOpen}
        noteTitle={notes.find((item) => item.note_id === selectedNoteId)?.note_title ?? "Untitled"}
        items={backlinks.items}
        isLoading={backlinks.isLoading}
        errorMessage={backlinks.errorMessage}
        onClose={backlinks.close}
        onRetry={() => {
          if (selectedNoteId) {
            backlinks.open(selectedNoteId);
          }
        }}
        onOpenSource={(noteId) => {
          backlinks.close();
          setSelectedNoteId(noteId);
          setHighlightedNoteId(noteId);
        }}
      />

      {qs.isOpen ? (
        <div
          className="quick-switch-overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              qs.close();
            }
          }}
        >
          <div
            className="quick-switch-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Quick switcher"
            onMouseDown={(event) => {
              event.stopPropagation();
            }}
          >
            <label className="sr-only" htmlFor="quick-switch-input">
              Quick switch
            </label>
            <input
              id="quick-switch-input"
              ref={qs.inputRef as React.RefObject<HTMLInputElement>}
              className="quick-switch-input"
              aria-label="Quick switch"
              type="text"
              value={qs.query}
              onChange={(event) => {
                qs.setQuery(event.target.value);
                qs.setSelectedIndex(0);
              }}
              onKeyDown={handleQuickSwitchKeyDown}
              placeholder="Search notes and actions"
            />

            <ul className="quick-switch-results" role="listbox" aria-label="Quick switch results">
              {qs.filteredItems.map((item, index) => (
                <li key={item.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === qs.selectedIndex}
                    className={`quick-switch-item${index === qs.selectedIndex ? " selected" : ""}`}
                    onMouseEnter={() => {
                      qs.setSelectedIndex(index);
                    }}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      void executeQuickSwitchItem(item);
                    }}
                  >
                    <span className="quick-switch-item-title">{item.title}</span>
                    {item.subtitle ? <span className="quick-switch-item-subtitle">{item.subtitle}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
            {qs.filteredItems.length === 0 ? (
              <p className="quick-switch-empty">No matches found.</p>
            ) : null}
          </div>
        </div>
      ) : null}

      {contextMenu ? (
        <ul
          ref={contextMenuRef}
          className="note-context-menu"
          role="menu"
          aria-label="Note actions"
          style={{ top: contextMenu.y, left: contextMenu.x }}
        >
          <li>
            <button type="button" role="menuitem" onClick={() => void handleRenameNote(contextMenu.noteId)}>
              Rename note
            </button>
          </li>
          <li>
            <button type="button" role="menuitem" onClick={() => void handleTogglePinnedNote(contextMenu.noteId)}>
              {contextNote?.is_pinned ? "Unpin note" : "Pin note"}
            </button>
          </li>
          <li>
            <button type="button" role="menuitem" onClick={() => void handleToggleArchivedNote(contextMenu.noteId)}>
              {contextNote?.is_archived ? "Unarchive note" : "Archive note"}
            </button>
          </li>
          <li>
            <button
              type="button"
              role="menuitem"
              className="danger"
              onClick={() => handleDeleteClick(contextMenu.noteId)}
            >
              Delete note
            </button>
          </li>
        </ul>
      ) : null}

      <InputModal
        isOpen={renameModalOpen}
        onClose={() => setRenameModalOpen(false)}
        onSubmit={handleRenameSubmit}
        title="Rename Note"
        label="Note title"
        initialValue={noteToRename?.note_title || ""}
        required
      />

      <ConfirmDialog
        isOpen={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        onConfirm={handleDeleteConfirm}
        title="Delete Note"
        message={`Are you sure you want to delete "${noteToDelete?.note_title}"? This action cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
      />
      <KeyboardShortcutsModal
        isOpen={shortcutsModalOpen}
        onClose={() => setShortcutsModalOpen(false)}
      />

      <ConfirmDialog
        isOpen={selection.bulkDeleteDialogOpen}
        title="Delete notes"
        message={`Delete ${selection.selectedNoteIds.size} note${selection.selectedNoteIds.size === 1 ? "" : "s"}? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={() => {
          void handleBulkDelete();
        }}
        onClose={() => selection.setBulkDeleteDialogOpen(false)}
      />

      <InputModal
        isOpen={selection.bulkTagDialogOpen}
        title="Add tag to selected notes"
        label="Tag"
        placeholder="e.g. ml"
        onClose={() => selection.setBulkTagDialogOpen(false)}
        onSubmit={(value) => {
          void handleBulkTag(value);
        }}
      />

      <InputModal
        isOpen={selection.bulkSubjectDialogOpen}
        title="Change subject for selected notes"
        label="Subject"
        placeholder="e.g. inbox"
        onClose={() => selection.setBulkSubjectDialogOpen(false)}
        onSubmit={(value) => {
          void handleBulkSubject(value);
        }}
      />
      <TemplateGallery
        isOpen={templateGalleryOpen}
        onClose={() => setTemplateGalleryOpen(false)}
        onSelect={(template) => {
          setTemplateGalleryOpen(false);
          void handleCreateNoteFromTemplate(template);
        }}
      />
      <QuickCaptureModal
        isOpen={quickCaptureOpen}
        onClose={() => setQuickCaptureOpen(false)}
        onSave={(result) => void handleQuickCaptureSave(result)}
      />
      <HelpWidget />
    </div>
  );
}
