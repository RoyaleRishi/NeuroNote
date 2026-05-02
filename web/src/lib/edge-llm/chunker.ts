/**
 * Pure-function note chunker for the streaming edge extraction pipeline.
 *
 * Splits long notes into overlapping windows so the LLM only ever sees
 * a small slice at a time. Splits prefer paragraph boundaries (\n\n),
 * fall back to sentence-end punctuation, and finally to hard character cuts.
 */

import type { NoteChunk } from "./types";

export interface ChunkOptions {
  /** Target number of characters per chunk. */
  targetSize: number;
  /** Characters of overlap between adjacent chunks. */
  overlap: number;
}

const SENTENCE_RE = /([.!?])\s+/g;

function splitOnRegex(text: string, re: RegExp): string[] {
  const parts: string[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const end = m.index! + m[0].length;
    parts.push(text.slice(last, end));
    last = end;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.filter((p) => p.length > 0);
}

/**
 * Hard-slice a piece that is itself larger than targetSize into sub-pieces.
 * Used as the final fallback when paragraph/sentence boundaries don't help.
 */
function hardSlice(piece: string, targetSize: number): string[] {
  if (piece.length <= targetSize) return [piece];
  const out: string[] = [];
  for (let i = 0; i < piece.length; i += targetSize) {
    out.push(piece.slice(i, i + targetSize));
  }
  return out;
}

function packIntoChunks(
  pieces: string[],
  opts: ChunkOptions,
  baseOffset: number,
): NoteChunk[] {
  const chunks: NoteChunk[] = [];
  let buf = "";
  let bufStart = baseOffset;
  let cursor = baseOffset;

  const flush = () => {
    const text = buf.trim();
    if (text.length === 0) return;
    chunks.push({ index: chunks.length, text, startOffset: bufStart });
    const tail = buf.length > opts.overlap ? buf.slice(-opts.overlap) : "";
    buf = tail;
    bufStart = cursor - tail.length;
  };

  // Pre-expand any oversized pieces via hard slicing so the packer's
  // boundary-only flush never has to emit a single piece bigger than target.
  const expanded: string[] = [];
  for (const piece of pieces) {
    for (const sub of hardSlice(piece, opts.targetSize)) {
      expanded.push(sub);
    }
  }

  for (const piece of expanded) {
    if (buf.length + piece.length > opts.targetSize && buf.length > 0) {
      flush();
    }
    buf += piece;
    cursor += piece.length;
  }
  flush();
  return chunks;
}

export function chunkNote(
  title: string,
  content: string,
  opts: ChunkOptions = { targetSize: 500, overlap: 50 },
): NoteChunk[] {
  const titleLine = title.trim();
  const body = content.trim();
  if (titleLine.length === 0 && body.length === 0) return [];

  const combined = titleLine ? `${titleLine}\n\n${body}` : body;

  if (combined.length <= opts.targetSize) {
    return [{ index: 0, text: combined, startOffset: 0 }];
  }

  const paragraphs = combined.split(/\n\n+/).map((p) => p + "\n\n");
  const paraChunks = packIntoChunks(paragraphs, opts, 0);
  const tooBig = paraChunks.some((c) => c.text.length > opts.targetSize * 1.5);
  if (!tooBig) return paraChunks.map((c, i) => ({ ...c, index: i }));

  const sentences = splitOnRegex(combined, SENTENCE_RE);
  const sentChunks = packIntoChunks(sentences, opts, 0);
  return sentChunks.map((c, i) => ({ ...c, index: i }));
}
