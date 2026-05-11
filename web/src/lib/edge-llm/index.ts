/**
 * Edge LLM inference module.
 *
 * Provides in-browser model inference via WebLLM + WebGPU.
 * Re-exports the public API surface.
 */

export {
  initializeEngine,
  getEngine,
  getModelStatus,
  isWebGPUSupported,
  type ModelStatus,
  type ModelProgress,
} from "./model-manager";

export { generateSummary, generateInsight } from "./inference-client";

export type { InsightRequest, InsightResult } from "./types";
