"use client";

/**
 * React hook owning the WebLLM engine lifecycle plus two UX gates:
 *
 *   1. Consent gating — first time edge mode is selected, hold the
 *      engine in 'awaiting-consent' until the user accepts or declines.
 *   2. Crash detection — if a previous session set the
 *      'edge-init-pending' flag and never cleared it, hold the engine
 *      in 'awaiting-recovery' until the user dismisses or switches.
 *
 * Both flags are persisted via `lib/edge-llm/persistence.ts`. The flag
 * for crash detection is set just before `initializeEngine()` and
 * cleared by the caller via `markStableInference()` after the first
 * successful inference completes.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  initializeEngine,
  isWebGPUSupported,
  type ModelProgress,
  type ModelStatus,
} from "../edge-llm/model-manager";
import {
  readConsent,
  writeConsent,
  readPendingFlag,
  writePendingFlag,
  clearPendingFlag,
  STALE_PENDING_MS,
} from "../edge-llm/persistence";

export interface UseEdgeLLMResult {
  status: ModelStatus;
  progress: ModelProgress | null;
  error: string | null;
  /** True once the engine has finished downloading and is ready for inference. */
  isReady: boolean;
  /** Called when the user accepts the consent dialog. Persists choice + starts init. */
  acceptConsent: () => void;
  /** Called when the user declines. Persists choice. Caller switches mode to cloud. */
  declineConsent: () => void;
  /** Dismiss the crash banner; either retry or switch to cloud. */
  acknowledgeRecovery: (action: "retry" | "switchToCloud") => void;
  /** Caller invokes after the first successful inference to clear the crash flag. */
  markStableInference: () => void;
}

export function useEdgeLLM(
  enabled: boolean,
  retryToken: number = 0,
): UseEdgeLLMResult {
  const [status, setStatus] = useState<ModelStatus>("idle");
  const [progress, setProgress] = useState<ModelProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Token bumped to retry the gating + init sequence after consent / recovery.
  const [internalToken, setInternalToken] = useState(0);

  // Whether the user has already cleared the pending flag this session — used
  // to avoid a second 'awaiting-recovery' after they retried.
  const recoveryHandledRef = useRef(false);

  const startInit = useCallback(() => {
    if (!isWebGPUSupported()) {
      setStatus("unsupported");
      setError("WebGPU is not available in this browser.");
      return;
    }
    setError(null);
    writePendingFlag(Date.now());
    void initializeEngine(
      (p) => setProgress(p),
      (s) => setStatus(s),
      (msg) => setError(msg),
    );
  }, []);

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      // Reset so a later re-enable still honours a fresh pending flag.
      recoveryHandledRef.current = false;
      return;
    }

    // 1. Consent gate.
    const consent = readConsent();
    if (consent !== "accepted") {
      setStatus("awaiting-consent");
      return;
    }

    // 2. Crash gate (only once per session).
    if (!recoveryHandledRef.current) {
      const pending = readPendingFlag();
      if (pending) {
        const age = Date.now() - pending.startedAt;
        if (age < STALE_PENDING_MS) {
          setStatus("awaiting-recovery");
          return;
        }
        // Stale — silently clear and proceed.
        clearPendingFlag();
      }
      recoveryHandledRef.current = true;
    }

    startInit();
  }, [enabled, retryToken, internalToken, startInit]);

  const acceptConsent = useCallback(() => {
    writeConsent("accepted");
    setInternalToken((n) => n + 1); // re-run the effect, this time consent is accepted
  }, []);

  const declineConsent = useCallback(() => {
    writeConsent("declined");
    setStatus("idle");
    // Caller is responsible for flipping llm_mode to cloud.
  }, []);

  const acknowledgeRecovery = useCallback(
    (action: "retry" | "switchToCloud") => {
      // Multi-tab note: clearing here and re-arming in startInit means two
      // tabs racing 'retry' can momentarily both pass the crash gate. The
      // model-manager singleton dedupes the actual engine init.
      clearPendingFlag();
      recoveryHandledRef.current = true;
      if (action === "switchToCloud") {
        setStatus("idle");
        // Caller is responsible for flipping llm_mode to cloud.
        return;
      }
      // Retry: re-run the effect, which will skip the recovery gate now.
      setInternalToken((n) => n + 1);
    },
    [],
  );

  const markStableInference = useCallback(() => {
    clearPendingFlag();
  }, []);

  return {
    status,
    progress,
    error,
    isReady: status === "ready",
    acceptConsent,
    declineConsent,
    acknowledgeRecovery,
    markStableInference,
  };
}
