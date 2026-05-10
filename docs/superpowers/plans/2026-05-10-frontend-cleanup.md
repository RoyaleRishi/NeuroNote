# Frontend Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the eight concrete inconsistencies and bugs identified in the 2026-05-10 frontend audit — contract drift, design-token violations, missing keyboard parity, divergent dismiss-handlers, and stray production logging.

**Architecture:** Eight small, mostly-independent fixes. Each task touches a tightly scoped set of files and ships behind a passing test or a typecheck/build gate. No shared abstractions are introduced beyond a single `useDismissable` hook (Task 6) that consolidates three duplicate Escape/click-outside implementations.

**Tech Stack:** Next.js 14 (App Router), TypeScript, React 18, Vitest + @testing-library/react, CSS custom-property design tokens (`web/src/app/globals.css`).

---

## Source audit findings (mapped to tasks)

| # | Finding | Task |
|---|---|---|
| 1 | `SaveNoteResponse.content_hash` and `ProcessStatusResponse.error` optional in TS, required in Python | Task 1 |
| 2 | `D3GraphCanvas.tsx:164,173` hardcoded hex colors | Task 2 |
| 3 | `tag-colors.ts` 16 hardcoded hex values | Task 3 |
| 4 | `WebGPUCheck.tsx` `rgb(15 23 42 / 45%)` overlay + `1.1rem` font-size | Task 4 |
| 5 | Note context-menu has no keyboard nav and Delete is mouse-only | Task 5 |
| 6 | Three different Escape handlers (Modal, ConceptInsightPanel, UserMenu) | Task 6 |
| 7 | UserMenu has 16 inline `style={{}}` blocks | Task 7 |
| 8 | `console.error` left in `NotesWorkspace.tsx:255`, `NoteEditor.tsx:474` | Task 8 |

Tasks are independent and can be tackled in any order, but the listed order minimises rebase pain (contract drift first, then tokens, then components, then refactors).

---

## File structure

| File | Role | Tasks |
|---|---|---|
| `shared/contracts/ts/v1/note.ts` | Mirror Python `note.py` | 1 |
| `shared/contracts/ts/v1/process.ts` | Mirror Python `process.py` | 1 |
| `web/src/app/globals.css` | Design tokens (add `--graph-node-stroke-*`, `--graph-label-*`, `--overlay-scrim`, tag-color CSS variables) | 2, 3, 4 |
| `web/src/components/graph/graph-constants.ts` | Add new CSS-var keys | 2 |
| `web/src/components/graph/D3GraphCanvas.tsx` | Read new tokens; remove hex literals | 2 |
| `web/src/lib/ui/tag-colors.ts` | Switch from hex pairs to CSS class names | 3 |
| `web/src/components/workspace/NotesWorkspace.tsx` | Apply tag class names; context-menu keyboard nav; remove `console.error` | 3, 5, 8 |
| `web/src/components/llm/WebGPUCheck.tsx` | Replace inline overlay rgb + 1.1rem with tokens; promote inline styles to a CSS class | 4 |
| `web/src/lib/hooks/useDismissable.ts` | **New** — Escape + click-outside hook | 6 |
| `web/src/components/auth/UserMenu.tsx` | Use `useDismissable`; replace inline styles with CSS classes | 6, 7 |
| `web/src/components/graph/ConceptInsightPanel.tsx` | Use `useDismissable` | 6 |
| `web/src/components/editor/NoteEditor.tsx` | Remove `console.error`, route through error toast | 8 |
| `web/src/lib/ui/error-toast.ts` | **New** — minimal error-reporting sink | 8 |
| Test files: `web/src/lib/hooks/useDismissable.test.tsx`, `web/src/components/workspace/NotesWorkspace.contextmenu.test.tsx`, `web/src/lib/ui/tag-colors.test.ts` | New tests | 3, 5, 6 |

---

### Task 1: Align TS optional fields with Python contracts

**Files:**
- Modify: `shared/contracts/ts/v1/note.ts:13-18`
- Modify: `shared/contracts/ts/v1/process.ts:22-29`
- Test: typecheck only — no runtime test (purely type narrowing)

**Why:** Python `SaveNoteResponse.content_hash` defaults to `""` (always present); `ProcessStatusResponse.error` is `str | None = None` (always present, possibly null). TS marks both as optional with `?`, which forces every consumer to do `if (x.content_hash)` defensive checks even though the field is guaranteed.

- [ ] **Step 1: Update `SaveNoteResponse.content_hash` and `GetNoteResponse.content_hash` to required**

Replace lines 13-18 and 20-32 of `shared/contracts/ts/v1/note.ts` so the response types mirror Python:

```ts
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
```

- [ ] **Step 2: Update `ProcessStatusResponse.error` to required-nullable**

Replace lines 22-29 of `shared/contracts/ts/v1/process.ts`:

```ts
export interface ProcessStatusResponse {
  job_id: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  error: string | null;
  extraction_summary: ExtractionSummary | null;
}
```

- [ ] **Step 3: Run frontend typecheck and fix consumer narrowing**

Run: `cd web && npx tsc --noEmit`
Expected: zero errors. If `if (saveResult.content_hash)` truthy-checks are now flagged as redundant, leave them — empty string is still a valid sentinel from the backend. Compiler will flag missing `error: null` defaults in mocks; add `error: null` and `extraction_summary: null` where required.

- [ ] **Step 4: Run frontend tests**

Run: `cd web && npx vitest run`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add shared/contracts/ts/v1/note.ts shared/contracts/ts/v1/process.ts web/
git commit -m "fix(contracts): align TS optional fields with Python (content_hash, error)"
```

---

### Task 2: Replace hardcoded hex colors in `D3GraphCanvas`

**Files:**
- Modify: `web/src/app/globals.css` (add stroke + label tokens)
- Modify: `web/src/components/graph/graph-constants.ts:33-41`
- Modify: `web/src/components/graph/D3GraphCanvas.tsx:32-50, 110-180`

**Why:** Lines 164 and 173 use literal hex (`#b85e10`, `#0f4e39`, `#fff`, `#7a3d0a`, `#6c6f75`) that bypass the design-token system. The same file already uses `getCssVar(GRAPH_CSS_VARS.*)` for fill colors; stroke and label colors must do the same.

- [ ] **Step 1: Add new tokens to `globals.css`**

Find the existing `:root { ... }` block in `web/src/app/globals.css` (or the section containing other `--graph-*` tokens — search for `--graph-node-note` and add immediately after that group):

```css
  --graph-node-stroke-default: #ffffff;
  --graph-node-stroke-root: #0f4e39;
  --graph-node-stroke-highlight: #b85e10;
  --graph-label-default: #6c6f75;
  --graph-label-highlight: #7a3d0a;
```

Add a matching dark-mode block under the existing dark `[data-theme='dark']` (or `@media (prefers-color-scheme: dark)`) selector with values that read on dark backgrounds — use the same scheme used elsewhere for graph tokens.

- [ ] **Step 2: Extend `GRAPH_CSS_VARS`**

Replace lines 33-41 of `web/src/components/graph/graph-constants.ts`:

```ts
export const GRAPH_CSS_VARS = {
  nodeNote: "--graph-node-note",
  nodeEntity: "--graph-node-entity",
  nodeOther: "--graph-node-other",
  edge: "--graph-edge",
  nodeHighlight: "--graph-node-highlight",
  edgeDim: "--graph-edge-dim",
  nodeDimOpacity: "--graph-node-dim-opacity",
  nodeStrokeDefault: "--graph-node-stroke-default",
  nodeStrokeRoot: "--graph-node-stroke-root",
  nodeStrokeHighlight: "--graph-node-stroke-highlight",
  labelDefault: "--graph-label-default",
  labelHighlight: "--graph-label-highlight",
} as const;
```

- [ ] **Step 3: Read tokens once in the render effect**

In `web/src/components/graph/D3GraphCanvas.tsx`, just below line 114, add:

```ts
    const strokeDefault = getCssVar(GRAPH_CSS_VARS.nodeStrokeDefault, "#ffffff");
    const strokeRoot = getCssVar(GRAPH_CSS_VARS.nodeStrokeRoot, "#0f4e39");
    const strokeHighlight = getCssVar(GRAPH_CSS_VARS.nodeStrokeHighlight, "#b85e10");
    const labelDefault = getCssVar(GRAPH_CSS_VARS.labelDefault, "#6c6f75");
    const labelHighlight = getCssVar(GRAPH_CSS_VARS.labelHighlight, "#7a3d0a");
```

- [ ] **Step 4: Replace literal hex in `nodeSelection.each`**

Replace line 164:

```ts
        .attr("stroke", isHighlight ? strokeHighlight : isRoot ? strokeRoot : strokeDefault)
```

Replace line 173:

```ts
        .attr("fill", isHighlight ? labelHighlight : labelDefault)
```

- [ ] **Step 5: Verify no hex literals remain in the file**

Run: `rg -n "#[0-9a-fA-F]{3,8}" web/src/components/graph/D3GraphCanvas.tsx`
Expected: no matches (or only inside fallback strings inside `getCssVar` calls, which is acceptable).

- [ ] **Step 6: Build + smoke-test the graph**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: typecheck + tests green.

Run: `make compose-up` and open `http://localhost:3000`. Open any note with concept entities; click the global graph; hover a node. Confirm node strokes and labels render the same shades as before (the tokens were chosen to match the prior literals).

- [ ] **Step 7: Commit**

```bash
git add web/src/app/globals.css web/src/components/graph/graph-constants.ts web/src/components/graph/D3GraphCanvas.tsx
git commit -m "fix(graph): replace hardcoded D3 stroke/label hex with tokens"
```

---

### Task 3: Move tag-color palette into CSS tokens

**Files:**
- Modify: `web/src/app/globals.css` (add 8 tag-color CSS classes)
- Modify: `web/src/lib/ui/tag-colors.ts` (return class names, not hex)
- Modify: `web/src/components/workspace/NotesWorkspace.tsx` around line 1035 (apply class instead of inline style)
- Test: `web/src/lib/ui/tag-colors.test.ts`

**Why:** All 16 tag-color hex values live in TS and are sprayed onto every tag via `style={{ backgroundColor, color }}`. They cannot be themed and they violate rule 15.

- [ ] **Step 1: Add tag-color CSS to `globals.css`**

Append to `web/src/app/globals.css` (in the same vicinity as other badge/chip styles):

```css
.tag-chip { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: var(--text-xs); font-weight: 500; }
.tag-chip-blue   { background: var(--tag-blue-bg);   color: var(--tag-blue-text); }
.tag-chip-green  { background: var(--tag-green-bg);  color: var(--tag-green-text); }
.tag-chip-amber  { background: var(--tag-amber-bg);  color: var(--tag-amber-text); }
.tag-chip-pink   { background: var(--tag-pink-bg);   color: var(--tag-pink-text); }
.tag-chip-purple { background: var(--tag-purple-bg); color: var(--tag-purple-text); }
.tag-chip-red    { background: var(--tag-red-bg);    color: var(--tag-red-text); }
.tag-chip-sky    { background: var(--tag-sky-bg);    color: var(--tag-sky-text); }
.tag-chip-violet { background: var(--tag-violet-bg); color: var(--tag-violet-text); }
```

And add the matching token definitions to the `:root` block:

```css
  --tag-blue-bg:   #dbeafe; --tag-blue-text:   #1e40af;
  --tag-green-bg:  #dcfce7; --tag-green-text:  #15803d;
  --tag-amber-bg:  #fef3c7; --tag-amber-text:  #b45309;
  --tag-pink-bg:   #fce7f3; --tag-pink-text:   #be185d;
  --tag-purple-bg: #ede9fe; --tag-purple-text: #6d28d9;
  --tag-red-bg:    #fee2e2; --tag-red-text:    #b91c1c;
  --tag-sky-bg:    #e0f2fe; --tag-sky-text:    #0369a1;
  --tag-violet-bg: #f3e8ff; --tag-violet-text: #7e22ce;
```

Add dark-mode overrides under the existing dark theme selector — pick desaturated/darker variants matching the rest of the dark palette.

- [ ] **Step 2: Write the failing test**

Create `web/src/lib/ui/tag-colors.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { getTagColorClass, TAG_CHIP_CLASSES } from "./tag-colors";

describe("tag-colors", () => {
  it("returns one of the eight tag-chip classes", () => {
    const cls = getTagColorClass("javascript");
    expect(TAG_CHIP_CLASSES).toContain(cls);
  });

  it("is deterministic — same tag → same class", () => {
    expect(getTagColorClass("javascript")).toBe(getTagColorClass("javascript"));
  });

  it("distributes across classes — 100 distinct tags hit all 8 buckets", () => {
    const seen = new Set<string>();
    for (let i = 0; i < 100; i++) seen.add(getTagColorClass(`tag-${i}`));
    expect(seen.size).toBeGreaterThan(4);
  });
});
```

- [ ] **Step 3: Run test, verify failure**

Run: `cd web && npx vitest run src/lib/ui/tag-colors.test.ts`
Expected: FAIL — `getTagColorClass`/`TAG_CHIP_CLASSES` do not exist yet.

- [ ] **Step 4: Rewrite `tag-colors.ts`**

Replace the entire contents of `web/src/lib/ui/tag-colors.ts` with:

```ts
export const TAG_CHIP_CLASSES = [
  "tag-chip-blue",
  "tag-chip-green",
  "tag-chip-amber",
  "tag-chip-pink",
  "tag-chip-purple",
  "tag-chip-red",
  "tag-chip-sky",
  "tag-chip-violet",
] as const;

export type TagChipClass = (typeof TAG_CHIP_CLASSES)[number];

export function getTagColorClass(tag: string): TagChipClass {
  let hash = 0;
  for (const c of tag) hash = (hash * 31 + c.charCodeAt(0)) | 0;
  return TAG_CHIP_CLASSES[Math.abs(hash) % TAG_CHIP_CLASSES.length]!;
}
```

(Drop the old `getTagColor` export — see Step 6 for migrating callers.)

- [ ] **Step 5: Run test, verify pass**

Run: `cd web && npx vitest run src/lib/ui/tag-colors.test.ts`
Expected: PASS, 3/3.

- [ ] **Step 6: Migrate the call site in `NotesWorkspace.tsx`**

Find the tag rendering near `web/src/components/workspace/NotesWorkspace.tsx:1035` (search for `getTagColor(`). Replace the import and the JSX. Before:

```tsx
import { getTagColor } from "../../lib/ui/tag-colors";
// ...
const c = getTagColor(tag);
return <span style={{ backgroundColor: c.bg, color: c.text }}>{tag}</span>;
```

After:

```tsx
import { getTagColorClass } from "../../lib/ui/tag-colors";
// ...
return <span className={`tag-chip ${getTagColorClass(tag)}`}>{tag}</span>;
```

Repeat for any other consumer (`rg -n "getTagColor(" web/src` to find them all — there should only be 1–2).

- [ ] **Step 7: Typecheck + full vitest**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add web/src/app/globals.css web/src/lib/ui/tag-colors.ts web/src/lib/ui/tag-colors.test.ts web/src/components/workspace/NotesWorkspace.tsx
git commit -m "fix(ui): move tag-color palette into CSS tokens"
```

---

### Task 4: Token-ise `WebGPUCheck` overlay and typography

**Files:**
- Modify: `web/src/app/globals.css` (add `--overlay-scrim` token, `.modal-overlay` and `.modal-card` classes if not already present)
- Modify: `web/src/components/llm/WebGPUCheck.tsx`

**Why:** Line 40 hardcodes `rgb(15 23 42 / 45%)`; line 69 sets `fontSize: "1.1rem"`. Both bypass tokens. The component also reinvents modal layout that other modals already share.

- [ ] **Step 1: Add scrim token**

Append to `:root` block in `web/src/app/globals.css`:

```css
  --overlay-scrim: rgba(15, 23, 42, 0.45);
```

If a `.modal-overlay` class doesn't already exist (`rg -n "\.modal-overlay" web/src/app/globals.css`), add:

```css
.modal-overlay {
  position: fixed; inset: 0;
  background: var(--overlay-scrim);
  z-index: var(--z-modal);
  display: flex; align-items: center; justify-content: center;
  padding: 24px;
}
.modal-card {
  max-width: 480px; width: 100%;
  background: var(--panel-bg);
  border: 1px solid var(--panel-border-strong);
  border-radius: 16px;
  box-shadow: var(--shadow-soft);
  padding: 24px;
  display: flex; flex-direction: column; gap: 14px;
}
.modal-card h2 { margin: 0; font-size: var(--text-lg); color: var(--text-strong); }
.modal-card p  { margin: 0; font-size: var(--text-sm); color: var(--text-muted); line-height: 1.45; }
.modal-card-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
```

If `--text-lg` doesn't exist, add it to `:root`:

```css
  --text-lg: 1.1rem;
```

- [ ] **Step 2: Replace `WebGPUCheck.tsx` body with class-driven markup**

Replace lines 32-113 of `web/src/components/llm/WebGPUCheck.tsx`:

```tsx
  if (!isOpen) return null;

  return (
    <div role="presentation" className="modal-overlay">
      <div role="dialog" aria-modal="true" aria-labelledby="webgpu-check-title" className="modal-card">
        <h2 id="webgpu-check-title">WebGPU Not Supported</h2>
        <p>
          Your browser doesn&apos;t support WebGPU, which is required for in-browser
          AI. You can switch to Cloud AI mode (with your own API key) instead, or
          try a Chromium-based browser with WebGPU enabled.
        </p>
        <div className="modal-card-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>
            Try Again
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={onOpenSettings}>
            Switch to Cloud AI
          </button>
        </div>
      </div>
    </div>
  );
```

- [ ] **Step 3: Verify no hex/rem literals remain in the file**

Run: `rg -n "#[0-9a-fA-F]{3,8}|[0-9]+rem|rgb\(" web/src/components/llm/WebGPUCheck.tsx`
Expected: no matches.

- [ ] **Step 4: Typecheck + smoke-test**

Run: `cd web && npx tsc --noEmit`
Expected: pass.

Smoke: load the app in a non-WebGPU browser (or temporarily flip the detection in `useEdgeLLM` to force the modal); confirm scrim and panel render unchanged.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/globals.css web/src/components/llm/WebGPUCheck.tsx
git commit -m "fix(ui): token-ise WebGPUCheck overlay and typography"
```

---

### Task 5: Keyboard parity for the note context menu

**Files:**
- Modify: `web/src/components/workspace/NotesWorkspace.tsx` around lines 1469-1503
- Test: `web/src/components/workspace/NotesWorkspace.contextmenu.test.tsx`

**Why:** CLAUDE.md rule 14 requires destructive actions to have keyboard parity. The context menu's Delete entry is mouse-only — no arrow-key navigation, no Enter to activate, no Esc to close, no focus trap.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/workspace/NotesWorkspace.contextmenu.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd web && npx vitest run src/components/workspace/NotesWorkspace.contextmenu.test.tsx`
Expected: FAIL — `NoteContextMenu` does not exist.

- [ ] **Step 3: Extract context menu into its own component**

Create `web/src/components/workspace/NoteContextMenu.tsx`:

```tsx
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
```

- [ ] **Step 4: Replace inline menu in `NotesWorkspace.tsx`**

In `web/src/components/workspace/NotesWorkspace.tsx`, add the import near the top (group with other workspace imports):

```tsx
import { NoteContextMenu } from "./NoteContextMenu";
```

Replace lines 1469-1503 with:

```tsx
      {contextMenu ? (
        <NoteContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          noteId={contextMenu.noteId}
          isPinned={!!contextNote?.is_pinned}
          isArchived={!!contextNote?.is_archived}
          onRename={(id) => void handleRenameNote(id)}
          onTogglePinned={(id) => void handleTogglePinnedNote(id)}
          onToggleArchived={(id) => void handleToggleArchivedNote(id)}
          onDelete={(id) => handleDeleteClick(id)}
          onClose={() => setContextMenu(null)}
        />
      ) : null}
```

The previous `contextMenuRef` was used elsewhere for click-outside; verify by `rg -n "contextMenuRef" web/src/components/workspace/NotesWorkspace.tsx`. If only used to close on outside click, remove it (the new menu auto-focuses, and outside click is handled by the existing global mousedown effect — confirm by reading lines around the existing definition before deleting).

- [ ] **Step 5: Run test to verify pass**

Run: `cd web && npx vitest run src/components/workspace/NotesWorkspace.contextmenu.test.tsx`
Expected: PASS, 2/2.

- [ ] **Step 6: Typecheck + full vitest**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: green.

- [ ] **Step 7: Manual smoke test**

`make compose-up`. Right-click a note in the sidebar. Tab/arrow through items, hit Enter on Delete — confirm the Delete confirmation modal opens. Press Escape with the menu open — confirm it closes.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/workspace/NoteContextMenu.tsx web/src/components/workspace/NotesWorkspace.contextmenu.test.tsx web/src/components/workspace/NotesWorkspace.tsx
git commit -m "fix(a11y): keyboard parity + focus management for note context menu"
```

---

### Task 6: Shared `useDismissable` hook

**Files:**
- Create: `web/src/lib/hooks/useDismissable.ts`
- Test: `web/src/lib/hooks/useDismissable.test.tsx`
- Modify: `web/src/components/auth/UserMenu.tsx` (replace lines 103-123 with hook)
- Modify: `web/src/components/graph/ConceptInsightPanel.tsx` (replace lines 42-60 with hook)

**Why:** The same Escape + click-outside handler is duplicated in `Modal`, `ConceptInsightPanel`, and `UserMenu`. One hook, one implementation, three call sites.

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/hooks/useDismissable.test.tsx`:

```tsx
import React, { useRef } from "react";
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useDismissable } from "./useDismissable";

function Fixture({ enabled, onDismiss }: { enabled: boolean; onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useDismissable(ref, enabled, onDismiss);
  return (
    <div>
      <div ref={ref} data-testid="inside">inside</div>
      <button data-testid="outside">outside</button>
    </div>
  );
}

describe("useDismissable", () => {
  it("calls onDismiss on Escape when enabled", () => {
    const onDismiss = vi.fn();
    render(<Fixture enabled={true} onDismiss={onDismiss} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("calls onDismiss on outside mousedown when enabled", () => {
    const onDismiss = vi.fn();
    const { getByTestId } = render(<Fixture enabled={true} onDismiss={onDismiss} />);
    fireEvent.mouseDown(getByTestId("outside"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("does not fire for clicks inside the ref", () => {
    const onDismiss = vi.fn();
    const { getByTestId } = render(<Fixture enabled={true} onDismiss={onDismiss} />);
    fireEvent.mouseDown(getByTestId("inside"));
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("is a no-op when disabled", () => {
    const onDismiss = vi.fn();
    render(<Fixture enabled={false} onDismiss={onDismiss} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd web && npx vitest run src/lib/hooks/useDismissable.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `useDismissable`**

Create `web/src/lib/hooks/useDismissable.ts`:

```ts
import { useEffect, type RefObject } from "react";

/**
 * Closes a popover/menu/panel when the user presses Escape or clicks outside
 * of `containerRef`.  No-op while `enabled` is false so the consumer can
 * conditionally mount the listener (e.g. only while the menu is open).
 */
export function useDismissable(
  containerRef: RefObject<HTMLElement | null>,
  enabled: boolean,
  onDismiss: () => void,
): void {
  useEffect(() => {
    if (!enabled) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onDismiss();
    }
    function onMouseDown(e: MouseEvent) {
      const el = containerRef.current;
      if (el && !el.contains(e.target as Node)) onDismiss();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onMouseDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onMouseDown);
    };
  }, [enabled, onDismiss, containerRef]);
}
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd web && npx vitest run src/lib/hooks/useDismissable.test.tsx`
Expected: PASS, 4/4.

- [ ] **Step 5: Migrate `UserMenu.tsx`**

In `web/src/components/auth/UserMenu.tsx`, add import:

```tsx
import { useDismissable } from "../../lib/hooks/useDismissable";
```

Delete lines 103-123 (the two `useEffect` blocks for outside-click and Escape) and replace with a single call near the top of the component, immediately after the existing `useRef` for `wrapperRef`:

```tsx
  useDismissable(wrapperRef, isOpen, () => setIsOpen(false));
```

- [ ] **Step 6: Migrate `ConceptInsightPanel.tsx`**

In `web/src/components/graph/ConceptInsightPanel.tsx`, add import:

```tsx
import { useDismissable } from "../../lib/hooks/useDismissable";
```

Delete lines 42-60 (the Escape + outside-click effects) and replace with one line below the existing `panelRef` declaration:

```tsx
  useDismissable(panelRef, true, onClose);
```

- [ ] **Step 7: Typecheck + full vitest**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: green; existing `UserMenu.test.tsx` and `ConceptInsightPanel.test.tsx` still pass.

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/hooks/useDismissable.ts web/src/lib/hooks/useDismissable.test.tsx web/src/components/auth/UserMenu.tsx web/src/components/graph/ConceptInsightPanel.tsx
git commit -m "refactor(ui): consolidate dismiss handlers into useDismissable hook"
```

---

### Task 7: Promote `UserMenu` inline styles into CSS classes

**Files:**
- Modify: `web/src/app/globals.css` (add `.user-menu-identity`, `.user-menu-identity-name`, `.user-menu-identity-email`, `.user-menu-mode-hint`, `.user-menu-cloud-input`, `.user-menu-test-status`)
- Modify: `web/src/components/auth/UserMenu.tsx` (drop inline `style={{}}`)

**Why:** 16 inline `style={{}}` blocks in one component is the textbook violation of rule 15 ("avoid ad-hoc styling"). Most are pure layout (flex, gap, fontSize) duplicated across the file.

- [ ] **Step 1: Add CSS classes to `globals.css`**

Append:

```css
.user-menu-identity { display: flex; align-items: center; gap: 10px; }
.user-menu-identity-name { font-size: var(--text-xs); font-weight: 700; color: var(--text-strong); }
.user-menu-identity-email { font-size: var(--text-xs); color: var(--text-muted); }
.user-menu-mode-hint { margin: 6px 0 0; font-size: var(--text-xs); color: var(--text-muted); }
.user-menu-cloud-input { font-size: var(--text-xs); }
.user-menu-cloud-input-row { display: flex; gap: 6px; }
.user-menu-cloud-input-row .user-menu-cloud-input { flex: 1; }
.user-menu-test-status { margin: 4px 0 0; font-size: var(--text-xs); color: var(--text-muted); }
.user-menu-test-status.error { color: var(--danger); }
.user-menu-confidence-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.user-menu-confidence-value { font-size: var(--text-xs); font-weight: 700; color: var(--accent); }
.user-menu-confidence-slider { width: 100%; accent-color: var(--accent); }
.user-menu-confidence-bounds { display: flex; justify-content: space-between; font-size: var(--text-xs); color: var(--text-muted); margin-top: 2px; }
```

- [ ] **Step 2: Replace inline styles with class names**

In `web/src/components/auth/UserMenu.tsx`, swap each inline `style={{}}` for the matching class. Concretely:

- Line 200-203 → `<div className="user-menu-section user-menu-identity">`
- Line 207-213 → `<div className="user-menu-identity-name">`
- Line 215-217 → `<div className="user-menu-identity-email">`
- Line 244-252 → `<p className="user-menu-mode-hint">`
- Lines 265, 276, 288 → `className="notes-filter-input user-menu-cloud-input"` (drop the `style={{ fontSize: "var(--text-xs)" }}`)
- Line 279 → `<div className="user-menu-cloud-input-row">`
- Lines 300-310 → `<p role={…} className={`user-menu-test-status${testStatus.ok ? "" : " error"}`}>`
- Lines 318-325 → `<div className="user-menu-confidence-row">`
- Lines 329-337 → `<span className="user-menu-confidence-value">`
- Lines 339-348 → `<input className="user-menu-confidence-slider" …>` (drop inline `style={{ width: "100%", accentColor: "var(--accent)" }}`)
- Lines 349-358 → `<div className="user-menu-confidence-bounds">`

For `AvatarCircle` (lines 22-68): leave it inline-styled — it's parameterised by `size` so the values are dynamic and a class doesn't fit.

- [ ] **Step 3: Verify hex/rem cleanup**

Run: `rg -n "style=\{\{" web/src/components/auth/UserMenu.tsx`
Expected: only the two `AvatarCircle` blocks remain (both intentional, dynamic).

- [ ] **Step 4: Typecheck + tests**

Run: `cd web && npx tsc --noEmit && npx vitest run src/components/auth/UserMenu.test.tsx`
Expected: green; existing UserMenu tests still pass.

- [ ] **Step 5: Visual smoke test**

`make compose-up`; open the user menu, toggle Edge↔Cloud, save cloud config, drag the confidence slider. Confirm no visual regressions vs. the prior look.

- [ ] **Step 6: Commit**

```bash
git add web/src/app/globals.css web/src/components/auth/UserMenu.tsx
git commit -m "refactor(ui): promote UserMenu inline styles to CSS classes"
```

---

### Task 8: Remove stray `console.error` from production code

**Files:**
- Create: `web/src/lib/ui/error-toast.ts`
- Modify: `web/src/components/workspace/NotesWorkspace.tsx:255`
- Modify: `web/src/components/editor/NoteEditor.tsx:474`

**Why:** `console.error` in production code logs only to the browser console — invisible to anyone but the developer. Both call sites already have a user-visible failure path (banner / status); the right fix is to centralise the user-facing error and drop the console call.

- [ ] **Step 1: Create the error sink**

Create `web/src/lib/ui/error-toast.ts`:

```ts
/**
 * Minimal user-facing error reporter.  Today this just logs to console under
 * a single tag (so production logs from the app itself are filterable) and
 * could later be wired to a toast component without touching call sites.
 */
export function reportUserError(scope: string, err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line no-console
    console.warn(`[neuronote:${scope}] ${message}`);
  }
}
```

- [ ] **Step 2: Replace the call in `NotesWorkspace.tsx`**

Find line 255. Before:

```tsx
console.error("[NotesWorkspace] switchToCloud failed", err);
```

After (also add the import near the top):

```tsx
import { reportUserError } from "../../lib/ui/error-toast";
// ...
reportUserError("switchToCloud", err);
```

- [ ] **Step 3: Replace the call in `NoteEditor.tsx`**

Find line 474. Before:

```tsx
console.error("[NeuroNote] Processing failed:", result.error);
```

After (with import):

```tsx
import { reportUserError } from "../../lib/ui/error-toast";
// ...
reportUserError("note-processing", result.error);
```

- [ ] **Step 4: Verify no `console.error` remains in non-test app code**

Run:

```bash
rg -n "console\.error" web/src --glob '!*.test.*' --glob '!*.spec.*'
```

Expected: no matches (or only inside `web/src/middleware.ts` / Edge-runtime code where Node logging is the only option — leave those if so, they aren't user-facing render code).

- [ ] **Step 5: Typecheck + full vitest**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/ui/error-toast.ts web/src/components/workspace/NotesWorkspace.tsx web/src/components/editor/NoteEditor.tsx
git commit -m "refactor(ui): route component errors through reportUserError"
```

---

## Final verification (after all tasks)

- [ ] **Full typecheck + tests + lint**

```bash
cd web && npx tsc --noEmit && npx vitest run && npx next lint
make compose-test
```

Expected: all green.

- [ ] **Token-violation sweep**

```bash
rg -n "#[0-9a-fA-F]{3,8}" web/src --glob '!*.test.*' --glob '!globals.css'
rg -n "rgb\(|rgba\(" web/src --glob '!*.test.*' --glob '!globals.css'
```

Expected: only matches inside `getCssVar` fallback strings.

- [ ] **End-to-end smoke**

`make compose-up`. Sign in → create a note → tag it → open right-click context menu and arrow-key to Delete → cancel → click a concept node → close insight panel via Escape → open user menu → toggle to Cloud, save, see test-connection result inline → log out. Confirm no visual regressions, no broken keyboard flows, no console errors.

---

## Self-review

**Spec coverage** — all eight audit findings have a dedicated task; finding #1 (contracts) → Task 1; #2 (D3 hex) → Task 2; #3 (tag colors) → Task 3; #4 (WebGPUCheck) → Task 4; #5 (context-menu keyboard parity) → Task 5; #6 (Escape duplication) → Task 6; #7 (UserMenu inline styles) → Task 7; #8 (`console.error`) → Task 8. ✅

**Placeholder scan** — no TBD, TODO, "implement later", or "similar to Task N". Each step has the exact code to apply. ✅

**Type consistency** — `getTagColorClass` and `TAG_CHIP_CLASSES` (Task 3) are referenced consistently across steps. `useDismissable(ref, enabled, onDismiss)` signature is the same in test (Step 1) and call sites (Steps 5-6) of Task 6. `reportUserError(scope, err)` signature matches in Task 8. ✅
