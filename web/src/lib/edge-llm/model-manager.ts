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
 * TODO: Replace with Gemma 4 E4B model ID once it is available in the
 * WebLLM model registry. For now, use the Gemma 2 2B quantised variant
 * as a development placeholder.
 */
const MODEL_ID = "gemma-2-2b-it-q4f16_1-MLC";

export type ModelStatus =
  | "idle"
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
