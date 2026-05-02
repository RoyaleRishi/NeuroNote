/**
 * High-level inference client for edge LLM tasks.
 *
 * Each function obtains the WebLLM engine from `model-manager`, constructs
 * prompts using the ported templates, and uses JSON-schema constrained
 * decoding to guarantee well-formed output.
 */
import { getEngine } from "./model-manager";
import {
  buildChunkExtractionPrompt,
  buildMetaPrompt,
  buildInsightPrompt,
} from "./prompts";
import { CHUNK_EXTRACTION_SCHEMA, META_SCHEMA, INSIGHT_SCHEMA } from "./schemas";
import type {
  ChunkExtractionRequest,
  ChunkExtractionResult,
  MetaClassificationRequest,
  MetaClassificationResult,
  InsightRequest,
  InsightResult,
} from "./types";

/**
 * Run the LLM "map" step for one note chunk.
 *
 * Returns indices into the candidates array (concepts to keep) plus
 * relation tuples. Bounded output size: max_tokens=256 is plenty
 * because the model emits integers, not full concept strings.
 */
export async function extractFromChunk(
  req: ChunkExtractionRequest,
): Promise<ChunkExtractionResult | null> {
  const engine = getEngine();
  if (!engine) {
    console.warn("[edge-llm] extractFromChunk: engine not initialised");
    return null;
  }

  if (req.candidates.length === 0) {
    return { keep: [], relations: [] };
  }

  const { system, user } = buildChunkExtractionPrompt(
    req.chunk.text,
    req.candidates,
    req.knownConcepts,
  );

  const t0 = performance.now();
  console.info("[edge-llm] extractFromChunk: starting", {
    chunkIdx: req.chunk.index,
    candidates: req.candidates.length,
    chunkLen: req.chunk.text.length,
  });

  let response;
  try {
    response = await engine.chat.completions.create({
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      temperature: 0.1,
      max_tokens: 256,
      response_format: {
        type: "json_object",
        schema: JSON.stringify(CHUNK_EXTRACTION_SCHEMA),
      },
    });
  } catch (err) {
    console.error("[edge-llm] extractFromChunk: inference threw", err);
    return null;
  }

  const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
  const text = response.choices[0]?.message?.content;
  console.info("[edge-llm] extractFromChunk: done", {
    chunkIdx: req.chunk.index,
    elapsedSeconds: elapsed,
    outputLen: text?.length ?? 0,
  });
  if (!text) return null;

  let parsed: { keep?: number[]; relations?: unknown[] };
  try {
    parsed = JSON.parse(text) as typeof parsed;
  } catch (err) {
    console.error(
      "[edge-llm] extractFromChunk: JSON parse failed",
      err,
      text.slice(0, 200),
    );
    return null;
  }

  const maxIdx = req.candidates.length;
  const keep = Array.isArray(parsed.keep)
    ? parsed.keep.filter(
        (n): n is number =>
          typeof n === "number" && Number.isInteger(n) && n >= 0 && n < maxIdx,
      )
    : [];

  const relations: ChunkExtractionResult["relations"] = [];
  if (Array.isArray(parsed.relations)) {
    for (const r of parsed.relations) {
      if (!Array.isArray(r) || r.length !== 3) continue;
      const [src, type, tgt] = r as [unknown, unknown, unknown];
      if (typeof src !== "number" || typeof tgt !== "number") continue;
      if (typeof type !== "string") continue;
      if (src < 0 || src >= maxIdx || tgt < 0 || tgt >= maxIdx) continue;
      if (src === tgt) continue;
      relations.push([
        src as number,
        type as ChunkExtractionResult["relations"][number][1],
        tgt as number,
      ]);
    }
  }

  return { keep, relations };
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

  const t0 = performance.now();
  console.info("[edge-llm] classifyMeta: starting", {
    conceptCount: req.concepts.length,
  });

  let response;
  try {
    response = await engine.chat.completions.create({
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
  } catch (err) {
    console.error("[edge-llm] classifyMeta: inference threw", err);
    return null;
  }

  const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
  const text = response.choices[0]?.message?.content;
  console.info("[edge-llm] classifyMeta: done", {
    elapsedSeconds: elapsed,
    outputLen: text?.length ?? 0,
  });
  if (!text) return null;

  try {
    const data = JSON.parse(text) as {
      synonym_pairs: Array<{ a: string; b: string }>;
      subtopic_pairs: Array<{ specific: string; broader: string }>;
    };
    return {
      synonymPairs: data.synonym_pairs ?? [],
      subtopicPairs: data.subtopic_pairs ?? [],
    };
  } catch (err) {
    console.error("[edge-llm] classifyMeta: JSON parse failed", err, text);
    return null;
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
