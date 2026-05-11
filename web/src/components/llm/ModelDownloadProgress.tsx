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
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        background: "var(--accent-soft)",
        borderBottom: "1px solid color-mix(in srgb, var(--accent) 30%, transparent)",
        padding: "10px 20px",
        display: "flex",
        flexDirection: "column",
        gap: "6px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "12px",
          fontSize: "var(--text-sm)",
          color: "var(--accent-ink)",
        }}
      >
        <strong>Downloading AI model... {pct}%</strong>
        <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>
          One-time download (~2GB). The model will be cached for future visits.
        </span>
      </div>
      <div
        aria-hidden="true"
        style={{
          height: "6px",
          width: "100%",
          background:
            "color-mix(in srgb, var(--accent) 18%, transparent)",
          borderRadius: "999px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: "var(--accent)",
            transition: "width 200ms ease-out",
          }}
        />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px" }}>
        <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>
          {detail}
        </span>
        <button
          type="button"
          onClick={() => void handleReset()}
          disabled={resetting}
          style={{
            fontSize: "var(--text-xs)",
            color: "var(--text-muted)",
            background: "transparent",
            border: "1px solid var(--panel-border)",
            borderRadius: "4px",
            padding: "0.2rem 0.5rem",
            cursor: resetting ? "default" : "pointer",
            opacity: resetting ? 0.5 : 1,
          }}
          title="Clear partial download and start over"
        >
          {resetting ? "Clearing..." : "Reset cache"}
        </button>
      </div>
    </div>
  );
}
