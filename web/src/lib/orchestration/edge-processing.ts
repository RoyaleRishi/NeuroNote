/**
 * Edge LLM processing orchestration.
 *
 * 1. Fetch server-generated candidates (POST /v1/extract-candidates).
 * 2. Pass candidates to in-browser Gemma for index-based filtering.
 * 3. Map indices back to concept strings.
 * 4. Generate one-sentence summary (separate Gemma call).
 * 5. Submit results + meta-classification to the API.
 *
 * The server is the single source of truth for candidate generation, so
 * cloud and edge modes always operate on an identical candidate pool.
 */

import { filterCandidates, generateSummary, classifyMeta } from "../edge-llm/inference-client";
import {
  fetchKnownConcepts,
  fetchCandidates,
  submitExtractionResults,
  submitMetaClassification,
} from "../api-client";

export interface EdgeProcessingRequest {
  baseUrl: string;
  noteId: string;
  noteTitle: string;
  contentText: string;
  contentHash: string;
  onProgress?: (done: number, total: number) => void;
  onChunkResult?: (concepts: string[]) => void;
}

export interface EdgeProcessingResult {
  status: "completed" | "failed";
  conceptCount?: number;
  relationCount?: number;
  chunksProcessed?: number;
  error?: string;
}

export async function runEdgeProcessing(
  request: EdgeProcessingRequest,
): Promise<EdgeProcessingResult> {
  try {
    const [known, candidateResp] = await Promise.all([
      fetchKnownConcepts(request.baseUrl),
      fetchCandidates(request.baseUrl, {
        note_id: request.noteId,
        title: request.noteTitle,
        content_text: request.contentText,
        content_hash: request.contentHash,
      }),
    ]);

    const { candidates } = candidateResp;

    if (candidates.length === 0) {
      request.onProgress?.(1, 1);
      return { status: "completed", conceptCount: 0, relationCount: 0, chunksProcessed: 1 };
    }

    const result = await filterCandidates(
      request.contentText,
      candidates,
      known.concepts,
    );
    request.onProgress?.(1, 1);

    if (!result) {
      return { status: "failed", error: "LLM inference returned null" };
    }

    const finalConcepts = result.keep
      .map((idx) => candidates[idx])
      .filter((c): c is string => c !== undefined)
      .map((text) => ({ text, confidence: 0.9 }));

    request.onChunkResult?.(finalConcepts.map((c) => c.text));

    const validRelations: Array<{
      source: string;
      type: string;
      target: string;
      confidence: number;
    }> = [];
    const relSeen = new Set<string>();
    for (const [srcIdx, type, tgtIdx] of result.relations) {
      const src = candidates[srcIdx];
      const tgt = candidates[tgtIdx];
      if (!src || !tgt || src === tgt) continue;
      const key = `${src}|${type}|${tgt}`;
      if (relSeen.has(key)) continue;
      relSeen.add(key);
      validRelations.push({ source: src, type, target: tgt, confidence: 0.85 });
    }

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
      chunksProcessed: 1,
    };
  } catch (error) {
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
