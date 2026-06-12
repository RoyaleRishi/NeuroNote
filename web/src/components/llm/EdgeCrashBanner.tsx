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
    <div role="status" aria-live="polite" className="edge-crash-banner">
      <span className="edge-crash-banner-message">
        <strong>⚠ Edge AI didn't finish loading last time.</strong>{" "}
        This usually means the device ran out of memory.
      </span>
      <button
        type="button"
        onClick={() => onAcknowledge("switchToCloud")}
        className="btn btn-sm btn-primary"
      >
        Switch to Cloud AI
      </button>
      <button
        type="button"
        onClick={() => onAcknowledge("retry")}
        className="btn btn-sm btn-secondary"
      >
        Try Edge AI again
      </button>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => onAcknowledge("retry")}
        className="edge-crash-banner-dismiss"
      >
        ×
      </button>
    </div>
  );
}
