/**
 * Edge LLM processing orchestration.
 *
 * Runs the in-browser extraction + meta-classification pipeline for a note,
 * mirroring the server-side flow used in cloud mode. Results are POSTed to
 * the API for graph synchronisation just as the cloud pipeline does on the
 * server.
 *
 * This module is the browser-side analogue of the server's
 * `process-note` → graph-sync → meta-classify flow. It does not download
 * or initialise the model itself — the caller is responsible for ensuring
 * the WebLLM engine is ready (see `useEdgeLLM`).
 */

import { extractConcepts, classifyMeta } from "../edge-llm/inference-client";
import {
  fetchKnownConcepts,
  submitExtractionResults,
  submitMetaClassification,
} from "../api-client";

export interface EdgeProcessingRequest {
  /** API base URL — required by the api-client wrappers. */
  baseUrl: string;
  noteId: string;
  noteTitle: string;
  contentText: string;
  /** Hash of the (title + content) used for cache invalidation. */
  contentHash: string;
}

export interface EdgeProcessingResult {
  status: "completed" | "failed";
  conceptCount?: number;
  relationCount?: number;
  error?: string;
}

/**
 * Run the full edge extraction pipeline for a note.
 *
 * Steps:
 *   1. Fetch the user's known concepts (used to bias the prompt).
 *   2. Run concept + relation extraction in the WebLLM worker.
 *   3. POST extraction results to the server for graph sync.
 *   4. Run meta-classification (synonym + subtopic) on the new concepts.
 *   5. POST meta-classification results to the server.
 *
 * Errors at any step short-circuit and return a failed result; the caller
 * is responsible for surfacing the error in the UI.
 */
export async function runEdgeProcessing(
  request: EdgeProcessingRequest,
): Promise<EdgeProcessingResult> {
  try {
    const known = await fetchKnownConcepts(request.baseUrl);

    const extraction = await extractConcepts({
      title: request.noteTitle,
      content: request.contentText,
      knownConcepts: known.concepts,
    });
    if (!extraction) {
      return { status: "failed", error: "Extraction returned null" };
    }

    await submitExtractionResults(request.baseUrl, {
      note_id: request.noteId,
      content_hash: request.contentHash,
      concepts: extraction.concepts,
      relations: extraction.relations,
      summary: extraction.summary,
    });

    const conceptTexts = extraction.concepts.map((c) => c.text);
    if (conceptTexts.length > 0) {
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
      conceptCount: extraction.concepts.length,
      relationCount: extraction.relations.length,
    };
  } catch (error) {
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
