/**
 * High-level inference client for edge LLM tasks.
 *
 * Each function obtains the WebLLM engine from `model-manager`, constructs
 * prompts using the ported templates, and uses JSON-schema constrained
 * decoding to guarantee well-formed output.
 */
import { getEngine } from "./model-manager";
import { buildSummaryPrompt, buildInsightPrompt } from "./prompts";
import { SUMMARY_SCHEMA, INSIGHT_SCHEMA } from "./schemas";
import type { SummaryRequest, InsightRequest, InsightResult } from "./types";

/**
 * Generate a one-sentence summary of a note.
 *
 * Runs after dedup so the summary can reference canonical concept names.
 * Bounded output (max_tokens=128) — model emits a short sentence; budget
 * has plenty of headroom.  Returns empty string on any failure so the
 * caller can submit `summary: ""` without branching.
 */
export async function generateSummary(req: SummaryRequest): Promise<string> {
  const engine = getEngine();
  if (!engine) return "";

  const { system, user } = buildSummaryPrompt(
    req.title,
    req.content,
    req.concepts,
  );

  const t0 = performance.now();
  console.info("[edge-llm] generateSummary: starting", {
    contentLen: req.content.length,
    conceptCount: req.concepts.length,
  });

  let response;
  try {
    response = await engine.chat.completions.create({
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      temperature: 0.3,
      max_tokens: 128,
      response_format: {
        type: "json_object",
        schema: JSON.stringify(SUMMARY_SCHEMA),
      },
    });
  } catch (err) {
    console.error("[edge-llm] generateSummary: inference threw", err);
    return "";
  }

  const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
  const text = response.choices[0]?.message?.content;
  console.info("[edge-llm] generateSummary: done", {
    elapsedSeconds: elapsed,
    outputLen: text?.length ?? 0,
  });
  if (!text) return "";

  try {
    const data = JSON.parse(text) as { summary?: unknown };
    return typeof data.summary === "string" ? data.summary : "";
  } catch (err) {
    console.error("[edge-llm] generateSummary: JSON parse failed", err, text);
    return "";
  }
}

/**
 * Generate an AI insight for a concept grounded in the user's notes.
 *
 * Returns null if the engine is not initialised or inference fails.
 */
export async function generateInsight(
  req: InsightRequest,
): Promise<InsightResult | null> {
  const engine = getEngine();
  if (!engine) return null;

  const { system, user } = buildInsightPrompt(
    req.conceptLabel,
    req.noteContexts.map((ctx) => ({
      title: ctx.title,
      excerpt: ctx.excerpt,
    })),
  );

  const response = await engine.chat.completions.create({
    messages: [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    temperature: 0.3,
    max_tokens: 1024,
    response_format: {
      type: "json_object",
      schema: JSON.stringify(INSIGHT_SCHEMA),
    },
  });

  const text = response.choices[0]?.message?.content;
  if (!text) return null;

  const data = JSON.parse(text) as {
    insight: string;
    learning_links: Array<{
      title: string;
      url: string;
      description: string;
    }>;
  };

  return {
    insight: data.insight,
    learningLinks: data.learning_links ?? [],
  };
}
