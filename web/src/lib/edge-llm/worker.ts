/**
 * Web Worker for WebLLM model inference.
 *
 * The worker delegates all message handling to WebLLM's built-in handler.
 * Complex logic (prompts, parsing, orchestration) stays in the main thread
 * via the `CreateWebWorkerMLCEngine` proxy.
 */
import { WebWorkerMLCEngineHandler } from "@mlc-ai/web-llm";

const handler = new WebWorkerMLCEngineHandler();
self.onmessage = (msg: MessageEvent) => {
  handler.onmessage(msg);
};
