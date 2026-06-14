"use client";

/**
 * Compact status badge shown in the workspace header indicating where note
 * summaries are written and (for on-device mode) model readiness. It does NOT
 * reflect the knowledge graph, which always runs on the server.
 *
 * Variants:
 *   - "Summaries: cloud" (cloud mode)
 *   - "Summaries: on-device (NN%)" (downloading)
 *   - "Summaries: on-device" (ready / idle)
 *   - "Summaries: on-device (WebGPU needed)" (browser doesn't support WebGPU)
 *   - "Summaries: on-device (error)" (initialisation failed)
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

type BadgeVariant =
  | "cloud"
  | "downloading"
  | "ready"
  | "unsupported"
  | "error"
  | "idle";

interface BadgeStyle {
  label: string;
  variant: BadgeVariant;
}

function styleFor(
  mode: "edge" | "cloud" | undefined | null,
  status: ModelStatus,
  progress: ModelProgress | null,
): BadgeStyle {
  if (mode === "cloud") {
    return { label: "Summaries: cloud", variant: "cloud" };
  }

  // On-device mode (or unknown — default to edge styling so users see progress).
  switch (status) {
    case "downloading": {
      const pct = Math.round((progress?.progress ?? 0) * 100);
      return { label: `Summaries: on-device (${pct}%)`, variant: "downloading" };
    }
    case "ready":
      return { label: "Summaries: on-device", variant: "ready" };
    case "unsupported":
      return { label: "Summaries: on-device (WebGPU needed)", variant: "unsupported" };
    case "error":
      return { label: "Summaries: on-device (error)", variant: "error" };
    case "idle":
    default:
      return { label: "Summaries: on-device", variant: "idle" };
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
      className={`model-status-indicator is-${style.variant}`}
    >
      <span
        aria-hidden="true"
        className={
          "model-status-indicator-dot" +
          (status === "downloading" ? " is-downloading" : "")
        }
      />
      {style.label}
    </span>
  );
}
