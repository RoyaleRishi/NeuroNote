"use client";

/**
 * Modal asking the user to choose between edge AI (in-browser) and
 * cloud AI (server with their API key). Shown once per browser, the
 * first time edge mode is selected, before any model download starts.
 *
 * Accepts via the "Use on-device" button. Declines via "Use cloud"
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
      className="edge-consent-overlay"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="edge-consent-panel"
      >
        <h2 id="edge-consent-title" className="edge-consent-title">
          Choose how note summaries are written
        </h2>
        <p className="edge-consent-subtitle">
          You can change this later in settings.
        </p>

        <div className="edge-consent-options">
          <div className="edge-consent-option">
            <strong className="edge-consent-option-title">
              🖥️ On-device (in your browser)
            </strong>
            <p className="edge-consent-option-desc">
              Summaries are written in your browser with Gemma — never sent to
              an outside AI provider. Uses ~2GB of memory; ~30s for long notes.
            </p>
          </div>

          <div className="edge-consent-option">
            <strong className="edge-consent-option-title">
              ☁️ Cloud (your API key)
            </strong>
            <p className="edge-consent-option-desc">
              Faster summaries on any device, using your OpenAI/Anthropic API
              key.
            </p>
          </div>
        </div>

        <p className="edge-consent-footnote">
          Either way, your concepts &amp; knowledge graph are built on your
          NeuroNote server.
        </p>

        <div className="edge-consent-actions">
          <button
            type="button"
            onClick={onDecline}
            className="btn btn-sm btn-secondary"
          >
            Use cloud
          </button>
          <button
            type="button"
            onClick={onAccept}
            className="btn btn-sm btn-primary"
          >
            Use on-device
          </button>
        </div>
      </div>
    </div>
  );
}
