"use client";

/**
 * React hook that owns the WebLLM engine lifecycle for a workspace.
 *
 * Behaviour:
 *   - When `enabled` is false, the hook is inert (no init triggered).
 *   - When `enabled` flips to true, the hook checks WebGPU support and
 *     either marks the status as `unsupported` or kicks off model
 *     initialisation.
 *   - Status and progress are mirrored into React state so they can drive
 *     UI components (status indicator, download banner, WebGPU modal).
 */

import { useEffect, useState } from "react";

import {
  initializeEngine,
  isWebGPUSupported,
  type ModelStatus,
  type ModelProgress,
} from "../edge-llm/model-manager";

export interface UseEdgeLLMResult {
  status: ModelStatus;
  progress: ModelProgress | null;
  /** Most recent error message from the engine (download/init failure). */
  error: string | null;
  /** True once the engine has finished downloading and is ready for inference. */
  isReady: boolean;
}

export function useEdgeLLM(
  enabled: boolean,
  /**
   * Bumping this token re-runs WebGPU detection and (if supported)
   * triggers another `initializeEngine` call. Used by the WebGPU
   * unsupported modal's "Try Again" button.
   */
  retryToken: number = 0,
): UseEdgeLLMResult {
  const [status, setStatus] = useState<ModelStatus>("idle");
  const [progress, setProgress] = useState<ModelProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    if (!isWebGPUSupported()) {
      setStatus("unsupported");
      setError("WebGPU is not available in this browser.");
      return;
    }
    setError(null);
    void initializeEngine(
      (p) => setProgress(p),
      (s) => setStatus(s),
      (msg) => setError(msg),
    );
  }, [enabled, retryToken]);

  return {
    status,
    progress,
    error,
    isReady: status === "ready",
  };
}
