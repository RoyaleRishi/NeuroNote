"use client";

/**
 * Modal shown when the user has selected edge mode but the browser does
 * not support WebGPU. Offers two paths forward:
 *   - "Switch to cloud" — opens the LLM settings modal so the user
 *     can flip the summaries mode toggle.
 *   - "Try Again" — re-checks WebGPU support (e.g. after the user has
 *     enabled an experimental flag in their browser).
 */

import React from "react";

interface WebGPUCheckProps {
  /** Whether the modal is visible. */
  isOpen: boolean;
  /** Open the LLM settings modal. */
  onOpenSettings: () => void;
  /**
   * Re-check WebGPU support; called when "Try Again" is clicked. The parent
   * is responsible for re-running detection (typically by bumping a retry
   * token consumed by `useEdgeLLM`).
   */
  onRetry: () => void;
}

export function WebGPUCheck({
  isOpen,
  onOpenSettings,
  onRetry,
}: WebGPUCheckProps) {
  if (!isOpen) return null;

  return (
    <div
      role="presentation"
      style={{
        position: "fixed",
        inset: 0,
        background: "var(--overlay-scrim)",
        zIndex: "var(--z-modal)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="webgpu-check-title"
        style={{
          maxWidth: "480px",
          width: "100%",
          background: "var(--panel-bg)",
          border: "1px solid var(--panel-border-strong)",
          borderRadius: "16px",
          boxShadow: "var(--shadow-soft)",
          padding: "24px",
          display: "flex",
          flexDirection: "column",
          gap: "14px",
        }}
      >
        <h2
          id="webgpu-check-title"
          style={{
            margin: 0,
            fontSize: "var(--text-lg)",
            color: "var(--text-strong)",
          }}
        >
          WebGPU Not Supported
        </h2>
        <p
          style={{
            margin: 0,
            fontSize: "var(--text-sm)",
            color: "var(--text-muted)",
            lineHeight: 1.45,
          }}
        >
          Your browser doesn&apos;t support WebGPU, which is required for
          on-device summaries. You can switch to cloud summaries (with your own
          API key) instead, or try a Chromium-based browser with WebGPU enabled.
        </p>
        <div
          style={{
            display: "flex",
            gap: "8px",
            justifyContent: "flex-end",
            marginTop: "4px",
          }}
        >
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onRetry}
          >
            Try Again
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={onOpenSettings}
          >
            Switch to cloud
          </button>
        </div>
      </div>
    </div>
  );
}
