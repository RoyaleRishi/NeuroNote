/**
 * High-level inference client for edge LLM tasks.
 *
 * Each function obtains the WebLLM engine from `model-manager`, constructs
 * prompts using the ported templates, and uses JSON-schema constrained
 * decoding to guarantee well-formed output.
 */
import { getEngine } from "./model-manager";
import {
  buildExtractionPrompt,
  buildMetaPrompt,
  buildInsightPrompt,
} from "./prompts";
import { EXTRACTION_SCHEMA, META_SCHEMA, INSIGHT_SCHEMA } from "./schemas";
import type {
  ExtractionRequest,
  ExtractionResult,
  MetaClassificationRequest,
  MetaClassificationResult,
  InsightRequest,
  InsightResult,
} from "./types";

/**
 * Extract concepts, relations, and summary from a note.
 *
 * Returns null if the engine is not initialised or inference fails.
 */
export async function extractConcepts(
  req: ExtractionRequest,
): Promise<ExtractionResult | null> {
  const engine = getEngine();
  if (!engine) return null;

  const { system, user } = buildExtractionPrompt(
    req.title,
    req.content,
    req.knownConcepts,
  );

  const response = await engine.chat.completions.create({
    messages: [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    temperature: 0.1,
    max_tokens: 2048,
    response_format: {
      type: "json_object",
      schema: JSON.stringify(EXTRACTION_SCHEMA),
    },
  });

  const text = response.choices[0]?.message?.content;
  if (!text) return null;

  return JSON.parse(text) as ExtractionResult;
}

/**
 * Classify synonym and subtopic pairs among a set of concepts.
 *
 * Returns null if the engine is not initialised or inference fails.
 */
export async function classifyMeta(
  req: MetaClassificationRequest,
): Promise<MetaClassificationResult | null> {
  const engine = getEngine();
  if (!engine) return null;

  if (req.concepts.length < 2) {
    return { synonymPairs: [], subtopicPairs: [] };
  }

  const { system, user } = buildMetaPrompt(req.concepts);

  const response = await engine.chat.completions.create({
    messages: [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    temperature: 0.1,
    max_tokens: 512,
    response_format: {
      type: "json_object",
      schema: JSON.stringify(META_SCHEMA),
    },
  });

  const text = response.choices[0]?.message?.content;
  if (!text) return null;

  const data = JSON.parse(text) as {
    synonym_pairs: Array<{ a: string; b: string }>;
    subtopic_pairs: Array<{ specific: string; broader: string }>;
  };

  return {
    synonymPairs: data.synonym_pairs ?? [],
    subtopicPairs: data.subtopic_pairs ?? [],
  };
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
