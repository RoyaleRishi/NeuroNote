"use client";

/**
 * Persistent banner shown across the top of the workspace while the WebLLM
 * model is downloading for the first time. Auto-hides once status is ready
 * (or while idle, in cloud mode, or unsupported — all handled by the parent
 * by passing the appropriate status).
 */

import React, { useState } from "react";
import {
  clearModelCache,
  type ModelStatus,
  type ModelProgress,
} from "../../lib/edge-llm/model-manager";

interface ModelDownloadProgressProps {
  status: ModelStatus;
  progress: ModelProgress | null;
}

export function ModelDownloadProgress({
  status,
  progress,
}: ModelDownloadProgressProps) {
  const [resetting, setResetting] = useState(false);

  if (status !== "downloading") return null;

  const pct = Math.round((progress?.progress ?? 0) * 100);
  const detail = progress?.text ?? "Preparing model...";

  const handleReset = async () => {
    if (!window.confirm(
      "Clear the cached model and reload? This will discard any partial download — you'll need to re-download the model.",
    )) return;
    setResetting(true);
    try {
      await clearModelCache();
    } finally {
      window.location.reload();
    }
  };

  return (
    <div role="status" aria-live="polite" className="model-download-progress">
      <div className="model-download-progress-header">
        <strong>Downloading AI model... {pct}%</strong>
        <span className="model-download-progress-hint">
          One-time download (~2GB). The model will be cached for future visits.
        </span>
      </div>
      <div aria-hidden="true" className="model-download-progress-bar">
        <div
          className="model-download-progress-bar-fill"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="model-download-progress-footer">
        <span className="model-download-progress-detail">{detail}</span>
        <button
          type="button"
          onClick={() => void handleReset()}
          disabled={resetting}
          className="model-download-progress-reset-btn"
          title="Clear partial download and start over"
        >
          {resetting ? "Clearing..." : "Reset cache"}
        </button>
      </div>
    </div>
  );
}
