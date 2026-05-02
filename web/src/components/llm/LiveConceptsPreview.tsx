"use client";

/**
 * Toolbar pill showing how many concepts have been streamed in so far,
 * with a click-to-expand popover listing them in insertion order.
 *
 * Pure presentation: parent passes `concepts` (already-deduped by the
 * parent's accumulator) and `isProcessing` (controls icon).
 *
 * Renders nothing while concepts is empty so the toolbar layout
 * doesn't shift on the first chunk.
 */

import React, { useState } from "react";

interface LiveConceptsPreviewProps {
  concepts: string[];
  /** Whether the pipeline is still running. Drives the icon (spinner vs check). */
  isProcessing: boolean;
}

export function LiveConceptsPreview({
  concepts,
  isProcessing,
}: LiveConceptsPreviewProps) {
  const [open, setOpen] = useState(false);

  if (concepts.length === 0) return null;

  const icon = isProcessing ? "⚙" : "✓";
  const label = `${concepts.length} concept${concepts.length === 1 ? "" : "s"} found`;

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          padding: "0.2rem 0.55rem",
          borderRadius: "999px",
          border: "1px solid var(--panel-border)",
          background: "var(--accent-soft)",
          color: "var(--accent-ink)",
          fontSize: "var(--text-xs)",
          fontWeight: 500,
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
        }}
      >
        <span aria-hidden="true">{icon}</span>
        {label}
        <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div
          role="region"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            zIndex: 100,
            minWidth: "200px",
            maxWidth: "320px",
            maxHeight: "240px",
            overflowY: "auto",
            background: "var(--panel-bg)",
            border: "1px solid var(--panel-border)",
            borderRadius: "6px",
            boxShadow: "var(--shadow-panel)",
            padding: "0.5rem",
          }}
        >
          <ul
            style={{
              margin: 0,
              padding: 0,
              listStyle: "none",
              fontSize: "var(--text-xs)",
              color: "var(--text-strong)",
            }}
          >
            {concepts.map((c, i) => (
              <li
                key={`${i}:${c}`}
                style={{
                  padding: "0.2rem 0.4rem",
                  borderBottom:
                    i < concepts.length - 1
                      ? "1px solid var(--panel-border)"
                      : "none",
                }}
              >
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
