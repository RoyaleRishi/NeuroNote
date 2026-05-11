import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Render a minimal context-menu fixture extracted to a small component for
// unit-testability.  The full NotesWorkspace is too heavy to mount in unit
// tests; this test exercises the keyboard-handler logic in isolation.
import { NoteContextMenu } from "./NoteContextMenu";

describe("NoteContextMenu — keyboard nav", () => {
  it("Escape closes the menu", () => {
    const onClose = vi.fn();
    render(
      <NoteContextMenu
        x={0} y={0} noteId="n1" isPinned={false} isArchived={false}
        onRename={vi.fn()} onTogglePinned={vi.fn()}
        onToggleArchived={vi.fn()} onDelete={vi.fn()} onClose={onClose}
      />,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("ArrowDown moves focus through menu items, Enter activates Delete", async () => {
    const onDelete = vi.fn();
    render(
      <NoteContextMenu
        x={0} y={0} noteId="n1" isPinned={false} isArchived={false}
        onRename={vi.fn()} onTogglePinned={vi.fn()}
        onToggleArchived={vi.fn()} onDelete={onDelete} onClose={vi.fn()}
      />,
    );
    const items = screen.getAllByRole("menuitem");
    await waitFor(() => expect(items[0]).toHaveFocus());
    fireEvent.keyDown(items[0]!, { key: "ArrowDown" });
    fireEvent.keyDown(items[1]!, { key: "ArrowDown" });
    fireEvent.keyDown(items[2]!, { key: "ArrowDown" });
    expect(items[3]).toHaveFocus();
    fireEvent.keyDown(items[3]!, { key: "Enter" });
    expect(onDelete).toHaveBeenCalledWith("n1");
  });
});
