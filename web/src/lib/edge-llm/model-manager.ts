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

/** Current model loading status. */
export function getModelStatus(): ModelStatus {
  return statusValue;
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
): Promise<WebWorkerMLCEngine | null> {
  if (engineInstance) return engineInstance;

  if (!isWebGPUSupported()) {
    statusValue = "unsupported";
    onStatusChange?.("unsupported");
    return null;
  }

  statusValue = "downloading";
  onStatusChange?.("downloading");

  try {
    const engine = await CreateWebWorkerMLCEngine(
      new Worker(new URL("./worker.ts", import.meta.url), { type: "module" }),
      MODEL_ID,
      {
        initProgressCallback: (progress) => {
          onProgress?.({
            text: progress.text,
            progress: progress.progress,
          });
        },
      },
    );

    engineInstance = engine;
    statusValue = "ready";
    onStatusChange?.("ready");
    return engine;
  } catch (err) {
    statusValue = "error";
    onStatusChange?.("error");
    console.error("Failed to initialize WebLLM engine:", err);
    return null;
  }
}
