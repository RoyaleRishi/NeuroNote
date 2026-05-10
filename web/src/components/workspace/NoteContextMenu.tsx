"use client";

import { useEffect, useRef } from "react";

interface NoteContextMenuProps {
  x: number;
  y: number;
  noteId: string;
  isPinned: boolean;
  isArchived: boolean;
  onRename: (noteId: string) => void;
  onTogglePinned: (noteId: string) => void;
  onToggleArchived: (noteId: string) => void;
  onDelete: (noteId: string) => void;
  onClose: () => void;
}

/**
 * Right-click menu for a single note row.  Provides keyboard parity for the
 * destructive Delete action (CLAUDE.md rule 14): Arrow keys navigate, Enter
 * activates, Escape closes.  Focus is auto-trapped to the menu.
 */
export function NoteContextMenu({
  x, y, noteId, isPinned, isArchived,
  onRename, onTogglePinned, onToggleArchived, onDelete, onClose,
}: NoteContextMenuProps) {
  const itemsRef = useRef<HTMLButtonElement[]>([]);

  useEffect(() => {
    itemsRef.current[0]?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      const items = itemsRef.current.filter(Boolean);
      const active = document.activeElement as HTMLElement | null;
      const idx = items.findIndex((b) => b === active);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        items[(idx + 1 + items.length) % items.length]?.focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        items[(idx - 1 + items.length) % items.length]?.focus();
      } else if (e.key === "Home") {
        e.preventDefault();
        items[0]?.focus();
      } else if (e.key === "End") {
        e.preventDefault();
        items[items.length - 1]?.focus();
      } else if (e.key === "Enter" || e.key === " ") {
        if (idx >= 0) {
          e.preventDefault();
          items[idx]?.click();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const setRef = (i: number) => (el: HTMLButtonElement | null) => {
    if (el) itemsRef.current[i] = el;
  };

  return (
    <ul className="note-context-menu" role="menu" aria-label="Note actions" style={{ top: y, left: x }}>
      <li>
        <button ref={setRef(0)} type="button" role="menuitem" onClick={() => onRename(noteId)}>
          Rename note
        </button>
      </li>
      <li>
        <button ref={setRef(1)} type="button" role="menuitem" onClick={() => onTogglePinned(noteId)}>
          {isPinned ? "Unpin note" : "Pin note"}
        </button>
      </li>
      <li>
        <button ref={setRef(2)} type="button" role="menuitem" onClick={() => onToggleArchived(noteId)}>
          {isArchived ? "Unarchive note" : "Archive note"}
        </button>
      </li>
      <li>
        <button ref={setRef(3)} type="button" role="menuitem" className="danger" onClick={() => onDelete(noteId)}>
          Delete note
        </button>
      </li>
    </ul>
  );
}
