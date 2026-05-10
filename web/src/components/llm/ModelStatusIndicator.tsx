"use client";

/**
 * Compact status badge shown in the workspace header indicating the
 * current AI mode and (for edge mode) model readiness.
 *
 * Variants:
 *   - "Cloud AI" (cloud mode)
 *   - "Edge AI: Loading NN%" (downloading)
 *   - "Edge AI: Ready"
 *   - "Edge AI: WebGPU Required" (browser doesn't support WebGPU)
 *   - "Edge AI: Error" (initialisation failed)
 */

import React from "react";
import type { ModelStatus, ModelProgress } from "../../lib/edge-llm/model-manager";

interface ModelStatusIndicatorProps {
  /** Current LLM mode from preferences. Null while preferences are loading. */
  mode: "edge" | "cloud" | undefined | null;
  /** Edge engine status (ignored when mode === "cloud"). */
  status: ModelStatus;
  /** Edge download progress (only meaningful when status === "downloading"). */
  progress: ModelProgress | null;
  /** Most recent error message (shown as tooltip when status is "error"). */
  error?: string | null;
}

interface BadgeStyle {
  label: string;
  bg: string;
  fg: string;
  border: string;
}

function styleFor(
  mode: "edge" | "cloud" | undefined | null,
  status: ModelStatus,
  progress: ModelProgress | null,
): BadgeStyle {
  if (mode === "cloud") {
    return {
      label: "Cloud AI",
      bg: "color-mix(in srgb, var(--info) 14%, transparent)",
      fg: "var(--info-text)",
      border: "color-mix(in srgb, var(--info) 35%, transparent)",
    };
  }

  // Edge mode (or unknown — default to edge styling so users see progress).
  switch (status) {
    case "downloading": {
      const pct = Math.round((progress?.progress ?? 0) * 100);
      return {
        label: `Edge AI: Loading ${pct}%`,
        bg: "color-mix(in srgb, var(--accent) 12%, transparent)",
        fg: "var(--accent-strong)",
        border: "color-mix(in srgb, var(--accent) 35%, transparent)",
      };
    }
    case "ready":
      return {
        label: "Edge AI: Ready",
        bg: "var(--accent-soft)",
        fg: "var(--accent-strong)",
        border: "color-mix(in srgb, var(--accent) 45%, transparent)",
      };
    case "unsupported":
      return {
        label: "Edge AI: WebGPU Required",
        bg: "color-mix(in srgb, var(--warning) 14%, transparent)",
        fg: "var(--warning-text)",
        border: "color-mix(in srgb, var(--warning) 40%, transparent)",
      };
    case "error":
      return {
        label: "Edge AI: Error",
        bg: "color-mix(in srgb, var(--danger) 14%, transparent)",
        fg: "var(--danger)",
        border: "color-mix(in srgb, var(--danger) 40%, transparent)",
      };
    case "idle":
    default:
      return {
        label: "Edge AI: Idle",
        bg: "transparent",
        fg: "var(--text-muted)",
        border: "var(--panel-border)",
      };
  }
}

export function ModelStatusIndicator({
  mode,
  status,
  progress,
  error,
}: ModelStatusIndicatorProps) {
  if (!mode) return null;
  const style = styleFor(mode, status, progress);
  const tooltip = error && (status === "error" || status === "unsupported")
    ? `${style.label} — ${error}`
    : style.label;

  return (
    <span
      role="status"
      aria-live="polite"
      title={tooltip}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        padding: "0.2rem 0.55rem",
        borderRadius: "999px",
        border: `1px solid ${style.border}`,
        background: style.bg,
        color: style.fg,
        fontSize: "var(--text-xs)",
        fontWeight: 500,
        whiteSpace: "nowrap",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: "currentColor",
          opacity: status === "downloading" ? 0.7 : 0.9,
        }}
      />
      {style.label}
    </span>
  );
}
