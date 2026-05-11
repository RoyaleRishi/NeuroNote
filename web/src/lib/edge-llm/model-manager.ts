/**
 * Manages the WebLLM engine lifecycle: download, initialization, and status.
 *
 * Singleton pattern — only one engine instance runs at a time.
 * Call `initializeEngine()` to start the download/load sequence;
 * use `getEngine()` to access the ready instance.
 */
import {
  CreateWebWorkerMLCEngine,
  type WebWorkerMLCEngine,
} from "@mlc-ai/web-llm";

/**
 * WebLLM model ID to load.
 *
 * Llama 3.2 3B Instruct (q4f16_1, ~2GB):
 *   - Officially in WebLLM's prebuilt registry (no custom config needed).
 *   - Trained for native function calling / structured JSON output.
 *   - Fits in ~2GB VRAM — works on most laptops with discrete GPUs or
 *     Apple Silicon.
 *
 * Gemma 4 E4B was the original target but is not yet published by
 * MLC for WebLLM (GitHub issue mlc-ai/web-llm#810 is still open as of
 * April 2026). Switch to a Gemma 4 model ID once it lands in the
 * prebuilt list.
 */
const MODEL_ID = "Llama-3.2-3B-Instruct-q4f16_1-MLC";

export type ModelStatus =
  | "idle"
  | "awaiting-consent"
  | "awaiting-recovery"
  | "downloading"
  | "ready"
  | "error"
  | "unsupported";

export interface ModelProgress {
  /** Human-readable status text from WebLLM (e.g. "Downloading params..."). */
  text: string;
  /** Progress value between 0 and 1. */
  progress: number;
}

let engineInstance: WebWorkerMLCEngine | null = null;
let statusValue: ModelStatus = "idle";
let lastErrorMessage: string | null = null;

/** Current model loading status. */
export function getModelStatus(): ModelStatus {
  return statusValue;
}

/** Most recent initialization error, or null. */
export function getLastError(): string | null {
  return lastErrorMessage;
}

/** The initialised engine, or null if not yet ready. */
export function getEngine(): WebWorkerMLCEngine | null {
  return engineInstance;
}

/** Clear all browser cache storage (including a partial/corrupted model download).
 *
 * Use this when a model download was interrupted and the next load hangs.
 * Disposes the engine instance so the next ``initializeEngine`` call
 * starts fresh.  Caller is responsible for triggering a page reload or
 * a re-init after this completes.
 */
export async function clearModelCache(): Promise<void> {
  // Tear down the engine first so its workers don't hold cache handles.
  if (engineInstance) {
    try {
      await engineInstance.unload();
    } catch {
      // ignore — engine may be in a bad state
    }
    engineInstance = null;
  }
  statusValue = "idle";
  lastErrorMessage = null;

  if (typeof caches === "undefined") return;
  const keys = await caches.keys();
  await Promise.all(keys.map((key) => caches.delete(key)));
}

/** Check whether the browser supports WebGPU. */
export function isWebGPUSupported(): boolean {
  return typeof navigator !== "undefined" && "gpu" in navigator;
}

/**
 * Download and initialise the WebLLM engine inside a Web Worker.
 *
 * Returns the engine on success, or null if WebGPU is unsupported or
 * initialisation fails. Safe to call multiple times — subsequent calls
 * return the existing engine.
 */
export async function initializeEngine(
  onProgress?: (p: ModelProgress) => void,
  onStatusChange?: (s: ModelStatus) => void,
  onError?: (message: string) => void,
): Promise<WebWorkerMLCEngine | null> {
  if (engineInstance) return engineInstance;

  if (!isWebGPUSupported()) {
    statusValue = "unsupported";
    lastErrorMessage = "WebGPU is not available in this browser.";
    onStatusChange?.("unsupported");
    return null;
  }

  // Probe the WebGPU adapter — Chrome reports "gpu" in navigator even when
  // the adapter request fails (e.g., insufficient VRAM, missing driver).
  try {
    // @ts-expect-error -- navigator.gpu is the WebGPU API
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) {
      statusValue = "unsupported";
      lastErrorMessage =
        "Could not request a WebGPU adapter. Your GPU may not be supported.";
      onStatusChange?.("unsupported");
      onError?.(lastErrorMessage);
      return null;
    }
  } catch (err) {
    statusValue = "unsupported";
    lastErrorMessage = `WebGPU adapter request failed: ${err instanceof Error ? err.message : String(err)}`;
    onStatusChange?.("unsupported");
    onError?.(lastErrorMessage);
    return null;
  }

  statusValue = "downloading";
  lastErrorMessage = null;
  onStatusChange?.("downloading");

  try {
    const worker = new Worker(
      new URL("./worker.ts", import.meta.url),
      { type: "module" },
    );

    // Surface worker errors so they don't disappear silently.
    worker.onerror = (event) => {
      const msg = event.message || "Worker error";
      console.error("[edge-llm worker]", msg, event);
      lastErrorMessage = `Worker error: ${msg}`;
      statusValue = "error";
      onStatusChange?.("error");
      onError?.(lastErrorMessage);
    };

    const engine = await CreateWebWorkerMLCEngine(worker, MODEL_ID, {
      initProgressCallback: (progress) => {
        onProgress?.({
          text: progress.text,
          progress: progress.progress,
        });
      },
    });

    engineInstance = engine;
    statusValue = "ready";
    lastErrorMessage = null;
    onStatusChange?.("ready");
    return engine;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    statusValue = "error";
    lastErrorMessage = message;
    onStatusChange?.("error");
    onError?.(message);
    console.error("Failed to initialize WebLLM engine:", err);
    return null;
  }
}
