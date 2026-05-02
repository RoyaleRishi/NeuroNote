/**
 * Edge LLM processing orchestration (chunked map-reduce pipeline).
 *
 * For each note:
 *   1. Chunk the (title + content) into ~500-char windows.
 *   2. Per chunk: rule-based candidate extraction → LLM filter by index → reducer input.
 *   3. After all chunks: dedupe across chunks.
 *   4. One short LLM call to generate a one-sentence summary.
 *   5. POST extraction results (concepts + relations + summary) to the API.
 *   6. Run meta-classification on the deduped concept list (synonym/subtopic).
 *
 * Each LLM call has bounded output, eliminating the mid-JSON truncation
 * that the previous one-shot extraction hit on long notes.
 */

import {
  extractFromChunk,
  generateSummary,
  classifyMeta,
} from "../edge-llm/inference-client";
import { chunkNote } from "../edge-llm/chunker";
import { extractCandidates } from "../edge-llm/candidates";
import { canonicalizeConcepts } from "../edge-llm/dedupe";
import {
  fetchKnownConcepts,
  submitExtractionResults,
  submitMetaClassification,
} from "../api-client";
import type {
  CanonicalConcept,
  RelationType,
} from "../edge-llm/types";

export interface EdgeProcessingRequest {
  baseUrl: string;
  noteId: string;
  noteTitle: string;
  contentText: string;
  contentHash: string;
  /** Optional progress callback: (chunksDone, totalChunks) -> void */
  onProgress?: (done: number, total: number) => void;
  /** Optional callback fired with new concepts after each chunk's LLM call. */
  onChunkResult?: (chunkConcepts: string[]) => void;
}

export interface EdgeProcessingResult {
  status: "completed" | "failed";
  conceptCount?: number;
  relationCount?: number;
  chunksProcessed?: number;
  error?: string;
}

interface RawRelation {
  source: string;
  type: RelationType;
  target: string;
}

export async function runEdgeProcessing(
  request: EdgeProcessingRequest,
): Promise<EdgeProcessingResult> {
  try {
    const known = await fetchKnownConcepts(request.baseUrl);

    const chunks = chunkNote(request.noteTitle, request.contentText);
    if (chunks.length === 0) {
      return {
        status: "completed",
        conceptCount: 0,
        relationCount: 0,
        chunksProcessed: 0,
      };
    }

    const allConcepts: CanonicalConcept[] = [];
    const allRelations: RawRelation[] = [];

    for (const chunk of chunks) {
      const candidates = extractCandidates(chunk.text);
      if (candidates.length === 0) {
        request.onProgress?.(chunk.index + 1, chunks.length);
        continue;
      }

      const result = await extractFromChunk({
        chunk,
        candidates,
        knownConcepts: known.concepts,
      });
      request.onProgress?.(chunk.index + 1, chunks.length);
      if (!result) continue;

      const chunkConcepts: string[] = [];
      for (const idx of result.keep) {
        const text = candidates[idx];
        if (!text) continue;
        allConcepts.push({
          text,
          confidence: 0.9,
          sources: [chunk.index],
        });
        chunkConcepts.push(text);
      }
      request.onChunkResult?.(chunkConcepts);

      for (const [srcIdx, type, tgtIdx] of result.relations) {
        const source = candidates[srcIdx];
        const target = candidates[tgtIdx];
        if (!source || !target) continue;
        allRelations.push({ source, type, target });
      }
    }

    // Reduce: dedupe concepts, then re-map relations to canonical surfaces.
    const canonical = canonicalizeConcepts(allConcepts);
    const canonicalKeys = new Map<string, string>();
    for (const c of canonical) {
      canonicalKeys.set(c.text.toLowerCase().trim(), c.text);
    }

    const findCanonical = (text: string): string | null => {
      const key = text.toLowerCase().trim();
      if (canonicalKeys.has(key)) return canonicalKeys.get(key)!;
      for (const c of canonical) {
        const ckey = c.text.toLowerCase();
        if (ckey.includes(key) || key.includes(ckey)) return c.text;
      }
      return null;
    };

    const validRelations: Array<{
      source: string;
      type: string;
      target: string;
      confidence: number;
    }> = [];
    const relSeen = new Set<string>();
    for (const r of allRelations) {
      const src = findCanonical(r.source);
      const tgt = findCanonical(r.target);
      if (!src || !tgt || src === tgt) continue;
      const key = `${src}|${r.type}|${tgt}`;
      if (relSeen.has(key)) continue;
      relSeen.add(key);
      validRelations.push({
        source: src,
        type: r.type,
        target: tgt,
        confidence: 0.85,
      });
    }

    const finalConcepts = canonical.map((c) => ({
      text: c.text,
      confidence: c.confidence,
    }));

    // Generate one-sentence summary so edge mode reaches feature parity
    // with cloud mode (which always populates summary). Failure returns "",
    // matching the previous behaviour — never blocks the submit.
    const summary = await generateSummary({
      title: request.noteTitle,
      content: request.contentText,
      concepts: finalConcepts.map((c) => c.text),
    });

    await submitExtractionResults(request.baseUrl, {
      note_id: request.noteId,
      content_hash: request.contentHash,
      concepts: finalConcepts,
      relations: validRelations,
      summary,
    });

    const conceptTexts = finalConcepts.map((c) => c.text);
    if (conceptTexts.length >= 2) {
      const meta = await classifyMeta({
        concepts: conceptTexts,
        knownConcepts: known.concepts,
      });
      if (meta) {
        await submitMetaClassification(request.baseUrl, {
          synonym_pairs: meta.synonymPairs,
          subtopic_pairs: meta.subtopicPairs,
          classified_concepts: conceptTexts,
        });
      }
    }

    return {
      status: "completed",
      conceptCount: finalConcepts.length,
      relationCount: validRelations.length,
      chunksProcessed: chunks.length,
    };
  } catch (error) {
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
