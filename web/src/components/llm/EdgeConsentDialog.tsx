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
      className="edge-consent-overlay"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="edge-consent-panel"
      >
        <h2 id="edge-consent-title" className="edge-consent-title">
          Choose how AI runs
        </h2>
        <p className="edge-consent-subtitle">
          You can change this later in settings.
        </p>

        <div className="edge-consent-options">
          <div className="edge-consent-option">
            <strong className="edge-consent-option-title">
              🖥️ Edge AI (in your browser)
            </strong>
            <p className="edge-consent-option-desc">
              Your notes never leave this device. Uses ~2GB of memory while you
              work. Processing takes ~30s for long notes.
            </p>
          </div>

          <div className="edge-consent-option">
            <strong className="edge-consent-option-title">
              ☁️ Cloud AI (your API key)
            </strong>
            <p className="edge-consent-option-desc">
              Faster. Works on any device. Requires an API key from
              OpenAI/Anthropic.
            </p>
          </div>
        </div>

        <div className="edge-consent-actions">
          <button
            type="button"
            onClick={onDecline}
            className="btn btn-sm btn-secondary"
          >
            Use Cloud AI
          </button>
          <button
            type="button"
            onClick={onAccept}
            className="btn btn-sm btn-primary"
          >
            Use Edge AI
          </button>
        </div>
      </div>
    </div>
  );
}
