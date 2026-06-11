"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDismissable } from "../../lib/hooks/useDismissable";

const SECTIONS = [
  {
    title: "Creating notes",
    items: [
      'Click "+ New note" to create a blank note.',
      'Use "From template" (▾ next to + New note) to start from a template.',
      "Give your note a title — it becomes the link target for other notes.",
    ],
  },
  {
    title: "Wiki links",
    items: [
      "Type [[ anywhere in the editor to link to another note.",
      "A fuzzy search dropdown appears — select or keep typing.",
      "Press Enter or click to insert the link.",
      "Linked notes appear in the Graph tab and in Linked mentions.",
    ],
  },
  {
    title: "Organizing",
    items: [
      "Open the ··· menu (top-right of the note) to set Subject, Tags, Pinned, or Archived.",
      "Use Subject to group notes by topic — e.g. 'work', 'research'.",
      "Tags are free-form labels — a note can have multiple tags.",
      "Filter notes by Subject or Tag using the dropdowns in the sidebar.",
    ],
  },
  {
    title: "Graph view",
    items: [
      "Click the Graph tab inside a note for its local knowledge graph.",
      "Click Graph in the top navigation for the full workspace graph.",
      "Nodes are notes, entities, and concepts extracted from content.",
      "Drag nodes to rearrange; scroll to zoom.",
    ],
  },
  {
    title: "Slash commands",
    items: [
      "Type / in the editor to open the command palette.",
      "Commands: headings, lists, code blocks, math, images, and more.",
      "Use arrow keys to navigate, Enter to apply.",
    ],
  },
  {
    title: "Keyboard shortcuts",
    items: [
      "Ctrl/⌘ + K — Quick switch between notes.",
      "Ctrl/⌘ + S — Save the current note.",
      "[ [ — Open wiki-link search.",
      "/ — Open command palette inside the editor.",
      "? — Open this help panel.",
    ],
  },
];

export function HelpWidget() {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Global `?` hotkey to toggle the panel — separate concern from dismissal.
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "?" && !["INPUT", "TEXTAREA"].includes((e.target as HTMLElement).tagName)) {
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, []);

  const close = useCallback(() => setOpen(false), []);
  useDismissable(dialogRef, open, close);

  return (
    <>
      <button
        type="button"
        className="help-widget-trigger"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Help"
        title="Help (press ?)"
      >
        ?
      </button>

      {open && (
        <div className="help-widget-overlay" aria-modal="true" role="dialog" aria-label="Help">
          <div ref={dialogRef} className="help-widget-panel">
            <div className="help-widget-header">
              <h2 className="help-widget-title">How to use NeuroNote</h2>
              <button
                type="button"
                className="help-widget-close"
                onClick={() => setOpen(false)}
                aria-label="Close help"
              >
                ×
              </button>
            </div>
            <div className="help-widget-body">
              {SECTIONS.map((section) => (
                <section key={section.title} className="help-widget-section">
                  <h3 className="help-widget-section-title">{section.title}</h3>
                  <ul className="help-widget-list">
                    {section.items.map((item) => (
                      <li key={item} className="help-widget-item">
                        {item}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
