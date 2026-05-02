"use client";

/**
 * Banner shown when a previous edge-mode session set the
 * 'edge-init-pending' flag and never cleared it (i.e. the tab was
 * killed mid-load). Lets the user switch to cloud mode in one click,
 * retry edge, or dismiss.
 *
 * Rendered above ModelDownloadProgress in NotesWorkspace.tsx.
 */

import React from "react";

interface EdgeCrashBannerProps {
  isOpen: boolean;
  onAcknowledge: (action: "retry" | "switchToCloud") => void;
}

export function EdgeCrashBanner({ isOpen, onAcknowledge }: EdgeCrashBannerProps) {
  if (!isOpen) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        background: "color-mix(in srgb, var(--danger) 14%, transparent)",
        borderBottom: "1px solid color-mix(in srgb, var(--danger) 35%, transparent)",
        padding: "10px 20px",
        display: "flex",
        alignItems: "center",
        gap: "12px",
        fontSize: "var(--text-sm)",
      }}
    >
      <span style={{ flex: 1, color: "var(--text-strong)" }}>
        <strong>⚠ Edge AI didn't finish loading last time.</strong>{" "}
        This usually means the device ran out of memory.
      </span>
      <button
        type="button"
        onClick={() => onAcknowledge("switchToCloud")}
        style={{
          padding: "0.3rem 0.75rem",
          fontSize: "var(--text-xs)",
          fontWeight: 600,
          color: "#fff",
          background: "var(--accent)",
          border: "1px solid var(--accent)",
          borderRadius: "4px",
          cursor: "pointer",
        }}
      >
        Switch to Cloud AI
      </button>
      <button
        type="button"
        onClick={() => onAcknowledge("retry")}
        style={{
          padding: "0.3rem 0.75rem",
          fontSize: "var(--text-xs)",
          fontWeight: 600,
          color: "var(--text-strong)",
          background: "transparent",
          border: "1px solid var(--panel-border)",
          borderRadius: "4px",
          cursor: "pointer",
        }}
      >
        Try Edge AI again
      </button>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => onAcknowledge("retry")}
        style={{
          padding: "0.2rem 0.5rem",
          fontSize: "var(--text-base)",
          color: "var(--text-muted)",
          background: "transparent",
          border: "none",
          cursor: "pointer",
        }}
      >
        ×
      </button>
    </div>
  );
}
