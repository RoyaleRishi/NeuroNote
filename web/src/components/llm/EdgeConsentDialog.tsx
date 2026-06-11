"use client";

/**
 * Modal asking the user to choose between edge AI (in-browser) and
 * cloud AI (server with their API key). Shown once per browser, the
 * first time edge mode is selected, before any model download starts.
 *
 * Accepts via the "Use Edge AI" button. Declines via "Use Cloud AI"
 * (caller is responsible for flipping `llm_mode` to "cloud").
 * Closing without choosing (Esc) leaves consent absent — the dialog
 * re-shows on next reload.
 */

import React, { useRef } from "react";
import { useDismissable } from "../../lib/hooks/useDismissable";

interface EdgeConsentDialogProps {
  isOpen: boolean;
  onAccept: () => void;
  onDecline: () => void;
  onDismiss: () => void;
}

export function EdgeConsentDialog({
  isOpen,
  onAccept,
  onDecline,
  onDismiss,
}: EdgeConsentDialogProps) {
  // Outside-click on the scrim already triggers onDismiss via onClick below,
  // so useDismissable's outside-mousedown is a no-op (ref spans the overlay)
  // and we rely on it solely for the Escape-key handler.
  const overlayRef = useRef<HTMLDivElement>(null);
  useDismissable(overlayRef, isOpen, onDismiss);

  if (!isOpen) return null;

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="edge-consent-title"
      onClick={onDismiss}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: "var(--z-modal)",
        background: "var(--overlay-scrim)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--panel-bg)",
          border: "1px solid var(--panel-border)",
          borderRadius: "12px",
          padding: "2rem",
          maxWidth: "480px",
          width: "100%",
          boxShadow: "var(--shadow-panel)",
        }}
      >
        <h2
          id="edge-consent-title"
          style={{
            margin: "0 0 0.5rem",
            fontSize: "1.25rem",
            fontWeight: 700,
            color: "var(--text-strong)",
          }}
        >
          Choose how AI runs
        </h2>
        <p
          style={{
            margin: "0 0 1.25rem",
            fontSize: "var(--text-sm)",
            color: "var(--text-muted)",
          }}
        >
          You can change this later in settings.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: "1rem", marginBottom: "1.5rem" }}>
          <div
            style={{
              padding: "0.75rem 1rem",
              border: "1px solid var(--panel-border)",
              borderRadius: "8px",
              background: "var(--workspace-surface)",
            }}
          >
            <strong style={{ color: "var(--text-strong)", fontSize: "var(--text-base)" }}>
              🖥️ Edge AI (in your browser)
            </strong>
            <p
              style={{
                margin: "0.25rem 0 0",
                fontSize: "var(--text-sm)",
                color: "var(--text-muted)",
                lineHeight: 1.5,
              }}
            >
              Your notes never leave this device. Uses ~2GB of memory while you
              work. Processing takes ~30s for long notes.
            </p>
          </div>

          <div
            style={{
              padding: "0.75rem 1rem",
              border: "1px solid var(--panel-border)",
              borderRadius: "8px",
              background: "var(--workspace-surface)",
            }}
          >
            <strong style={{ color: "var(--text-strong)", fontSize: "var(--text-base)" }}>
              ☁️ Cloud AI (your API key)
            </strong>
            <p
              style={{
                margin: "0.25rem 0 0",
                fontSize: "var(--text-sm)",
                color: "var(--text-muted)",
                lineHeight: 1.5,
              }}
            >
              Faster. Works on any device. Requires an API key from
              OpenAI/Anthropic.
            </p>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={onDecline}
            style={{
              padding: "0.5rem 1rem",
              fontSize: "var(--text-sm)",
              fontWeight: 600,
              color: "var(--text-strong)",
              background: "transparent",
              border: "1px solid var(--panel-border)",
              borderRadius: "6px",
              cursor: "pointer",
            }}
          >
            Use Cloud AI
          </button>
          <button
            type="button"
            onClick={onAccept}
            style={{
              padding: "0.5rem 1rem",
              fontSize: "var(--text-sm)",
              fontWeight: 600,
              color: "var(--text-on-accent)",
              background: "var(--accent)",
              border: "1px solid var(--accent)",
              borderRadius: "6px",
              cursor: "pointer",
            }}
          >
            Use Edge AI
          </button>
        </div>
      </div>
    </div>
  );
}
