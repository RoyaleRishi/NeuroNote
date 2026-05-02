# Streaming Edge Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the failing one-shot LLM extraction with a chunked map-reduce pipeline so notes of any length yield clean concepts and relations without truncation.

**Architecture:** Split the note into ~500-char windows. For each window, a regex-based candidate extractor over-generates noun phrases. The LLM receives the chunk + numbered candidates and emits a tiny JSON of integer indices to keep + relations between them. After all chunks are processed, a deterministic reducer dedupes and canonicalizes. This bounds every LLM call to ~200 tokens, eliminating the truncation failures from the existing `extractConcepts` flow.

**Tech Stack:** TypeScript, `@mlc-ai/web-llm` (Llama 3.2 3B), Vitest for unit tests, no new runtime dependencies.

---

## Failure mode being fixed

Console output (current impl) for a 3,000-char JS notes file:

```
[edge-llm] extractConcepts: done {elapsedSeconds: "..." outputLen: ~3500}
[edge-llm] extractConcepts: JSON parse failed
SyntaxError: JSON Parse error: Property name must be a string literal
"...
\"source\": \"functional programming\",
\"type\": \"IS_A\",     // <- output stops mid-object
"
```

The model emits 22 concepts and starts a relations list of similar size. It hits `max_tokens=1024` mid-relation, leaving the JSON unterminated. WebLLM's grammar-constrained decoding does not save us — it ran out of budget.

## Reference

- KGGen (arXiv 2502.09956): "over-generate-then-cluster" pattern, +18pt accuracy over GraphRAG on small models
- Microsoft GraphRAG: 50–100 token chunks, flat extraction + post-hoc clustering
- Each LLM call output bounded to ~150 tokens of integers (indices), not strings

---

## File structure

**New files:**

- `web/src/lib/edge-llm/chunker.ts` — pure: split note text into overlapping windows
- `web/src/lib/edge-llm/candidates.ts` — pure: regex-based noun-phrase candidate extraction
- `web/src/lib/edge-llm/dedupe.ts` — pure: canonicalize + merge concepts across chunks
- `web/src/lib/edge-llm/chunk-extraction.ts` — orchestrate one chunk's LLM "map" step
- `web/src/lib/edge-llm/__tests__/chunker.test.ts`
- `web/src/lib/edge-llm/__tests__/candidates.test.ts`
- `web/src/lib/edge-llm/__tests__/dedupe.test.ts`

**Modified files:**

- `web/src/lib/edge-llm/schemas.ts` — replace EXTRACTION_SCHEMA with `CHUNK_EXTRACTION_SCHEMA` (indices + integer-tuple relations)
- `web/src/lib/edge-llm/prompts.ts` — replace `EXTRACTION_SYSTEM_PROMPT` + `buildExtractionPrompt` with `buildChunkExtractionPrompt`
- `web/src/lib/edge-llm/inference-client.ts` — replace `extractConcepts` with `extractFromChunk` calling the new prompt + schema
- `web/src/lib/orchestration/edge-processing.ts` — orchestrate chunk-by-chunk loop with progress reporting
- `web/src/lib/edge-llm/types.ts` — add per-chunk request/result types

---

## Type contracts (used across tasks)

These are the types tasks below will create. All defined in `web/src/lib/edge-llm/types.ts`:

```typescript
export interface NoteChunk {
  /** 0-based chunk index. */
  index: number;
  /** The chunk's text content. */
  text: string;
  /** Character offset of chunk start in the full note. */
  startOffset: number;
}

export interface ChunkExtractionRequest {
  chunk: NoteChunk;
  candidates: string[];
  knownConcepts: string[];
}

export type RelationType =
  | "IS_A" | "PART_OF" | "CAUSES" | "CONTRASTS_WITH"
  | "USES" | "PRODUCES" | "RELATED_TO";

/** LLM output for one chunk. Integer indices into the candidates array. */
export interface ChunkExtractionResult {
  /** Indices of candidates to keep as concepts. */
  keep: number[];
  /** Tuples of (sourceIdx, relationType, targetIdx). */
  relations: Array<[number, RelationType, number]>;
}

/** A canonical concept after dedup, with provenance. */
export interface CanonicalConcept {
  /** Canonical surface form (longest variant kept). */
  text: string;
  /** Best confidence among merged variants. */
  confidence: number;
  /** Chunk indices this concept appeared in. */
  sources: number[];
}
```

Note: the existing `ExtractionResult` (full text-based concepts) stays — that's what we POST to the server. The pipeline is: chunk → LLM emits `ChunkExtractionResult` (indices) → reducer outputs `CanonicalConcept[]` → orchestrator converts to `ExtractionResult` for the API.

---

## Task 1: Add the new types

**Files:**
- Modify: `web/src/lib/edge-llm/types.ts`

- [ ] **Step 1: Add new types to the existing file**

Append to `web/src/lib/edge-llm/types.ts` (do NOT remove existing types yet — `ExtractionResult` is still used as the final output shape):

```typescript
export interface NoteChunk {
  /** 0-based chunk index. */
  index: number;
  /** The chunk's text content. */
  text: string;
  /** Character offset of chunk start in the full note. */
  startOffset: number;
}

export interface ChunkExtractionRequest {
  chunk: NoteChunk;
  candidates: string[];
  knownConcepts: string[];
}

export type RelationType =
  | "IS_A"
  | "PART_OF"
  | "CAUSES"
  | "CONTRASTS_WITH"
  | "USES"
  | "PRODUCES"
  | "RELATED_TO";

export interface ChunkExtractionResult {
  /** Indices of candidates the LLM kept as real concepts. */
  keep: number[];
  /** Tuples of (sourceIdx, relationType, targetIdx) — both indices into candidates. */
  relations: Array<[number, RelationType, number]>;
}

export interface CanonicalConcept {
  text: string;
  confidence: number;
  sources: number[];
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/edge-llm/types.ts
git commit -m "edge-llm: add chunk-level extraction types

Adds NoteChunk, ChunkExtractionRequest, ChunkExtractionResult, and
CanonicalConcept. Existing ExtractionResult is unchanged — it remains
the final output shape POSTed to /v1/extraction-results."
```

---

## Task 2: Chunker (pure function + unit tests)

**Files:**
- Create: `web/src/lib/edge-llm/chunker.ts`
- Create: `web/src/lib/edge-llm/__tests__/chunker.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/src/lib/edge-llm/__tests__/chunker.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { chunkNote } from "../chunker";

describe("chunkNote", () => {
  it("returns a single chunk for short input", () => {
    const chunks = chunkNote("Title", "Short body.", { targetSize: 500, overlap: 50 });
    expect(chunks).toHaveLength(1);
    expect(chunks[0]).toEqual({
      index: 0,
      text: "Title\n\nShort body.",
      startOffset: 0,
    });
  });

  it("splits long input on paragraph boundaries", () => {
    const para = "x".repeat(300);
    const content = `${para}\n\n${para}\n\n${para}`;
    const chunks = chunkNote("", content, { targetSize: 400, overlap: 50 });
    expect(chunks.length).toBeGreaterThanOrEqual(2);
    // every chunk text length within ~targetSize+overlap
    for (const c of chunks) {
      expect(c.text.length).toBeLessThanOrEqual(500);
    }
    // chunks are indexed 0..n-1
    expect(chunks.map((c) => c.index)).toEqual(
      Array.from({ length: chunks.length }, (_, i) => i),
    );
  });

  it("falls back to sentence boundaries when paragraphs are too long", () => {
    const big = Array.from({ length: 6 }, () => "Sentence one. Sentence two. Sentence three.").join(" ");
    const chunks = chunkNote("", big, { targetSize: 60, overlap: 10 });
    expect(chunks.length).toBeGreaterThan(1);
  });

  it("includes overlap between adjacent chunks", () => {
    const para = "abcdefghij".repeat(60); // 600 chars
    const chunks = chunkNote("", para, { targetSize: 200, overlap: 30 });
    // Some character should appear in two chunks (the overlap region).
    const chars = new Set(chunks[0]!.text.slice(-30));
    const next = chunks[1]!.text.slice(0, 30);
    let hit = 0;
    for (const ch of next) if (chars.has(ch)) hit++;
    expect(hit).toBeGreaterThan(10);
  });

  it("never produces an empty chunk", () => {
    const chunks = chunkNote("", "", { targetSize: 500, overlap: 50 });
    // Empty input => empty output, not [{ text: "" }].
    expect(chunks).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/edge-llm/__tests__/chunker.test.ts`
Expected: FAIL with "cannot find module '../chunker'"

- [ ] **Step 3: Implement the chunker**

Create `web/src/lib/edge-llm/chunker.ts`:

```typescript
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
    // Preserve overlap: keep the last `opts.overlap` chars as the seed of the next buffer.
    const tail = buf.length > opts.overlap ? buf.slice(-opts.overlap) : "";
    buf = tail;
    bufStart = cursor - tail.length;
  };

  for (const piece of pieces) {
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

  // 1. Try paragraph splits first.
  const paragraphs = combined.split(/\n\n+/).map((p) => p + "\n\n");
  const paraChunks = packIntoChunks(paragraphs, opts, 0);
  // If any single chunk is still too big, fall back to sentence-level splitting on
  // that chunk's text and re-pack from scratch.
  const tooBig = paraChunks.some((c) => c.text.length > opts.targetSize * 1.5);
  if (!tooBig) return paraChunks.map((c, i) => ({ ...c, index: i }));

  const sentences = splitOnRegex(combined, SENTENCE_RE);
  const sentChunks = packIntoChunks(sentences, opts, 0);
  return sentChunks.map((c, i) => ({ ...c, index: i }));
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/lib/edge-llm/__tests__/chunker.test.ts`
Expected: 5/5 pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/edge-llm/chunker.ts web/src/lib/edge-llm/__tests__/chunker.test.ts
git commit -m "edge-llm: chunker for streaming extraction

Splits notes into ~500-char windows on paragraph then sentence
boundaries, with 50-char overlap. Pure function, no LLM. Used by
the new map-reduce extraction pipeline."
```

---

## Task 3: Candidate extractor (rule-based, no LLM)

**Files:**
- Create: `web/src/lib/edge-llm/candidates.ts`
- Create: `web/src/lib/edge-llm/__tests__/candidates.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/src/lib/edge-llm/__tests__/candidates.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { extractCandidates } from "../candidates";

describe("extractCandidates", () => {
  it("extracts wiki-link targets", () => {
    const result = extractCandidates("Talks about [[Machine Learning]] and [[AI]].");
    expect(result).toEqual(expect.arrayContaining(["Machine Learning", "AI"]));
  });

  it("extracts capitalised phrases", () => {
    const result = extractCandidates("Just-In-Time compilation runs at runtime.");
    expect(result).toEqual(expect.arrayContaining(["Just-In-Time"]));
  });

  it("extracts acronyms", () => {
    const result = extractCandidates("JSON, HTML, and CSS are common.");
    expect(result).toEqual(expect.arrayContaining(["JSON", "HTML", "CSS"]));
  });

  it("extracts hyphenated technical compounds", () => {
    const result = extractCandidates("It's a non-blocking event-loop language.");
    expect(result).toEqual(
      expect.arrayContaining(["non-blocking", "event-loop"]),
    );
  });

  it("dedupes case-insensitively but preserves first-seen surface form", () => {
    const result = extractCandidates("CSS is great. css is great. Css again.");
    // Only one of CSS/css/Css should appear.
    const lower = result.map((c) => c.toLowerCase());
    expect(lower.filter((c) => c === "css")).toHaveLength(1);
  });

  it("filters out short tokens and stopwords", () => {
    const result = extractCandidates("It is a good thing.");
    // Should not include "It", "is", "a", "good", "thing" — none are
    // capitalised phrases, acronyms, or hyphenated compounds beyond noise.
    expect(result.length).toBeLessThanOrEqual(0);
  });

  it("returns at most 30 candidates per chunk", () => {
    const big = Array.from({ length: 60 }, (_, i) => `Topic${i}`).join(" ");
    const result = extractCandidates(big);
    expect(result.length).toBeLessThanOrEqual(30);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/lib/edge-llm/__tests__/candidates.test.ts`
Expected: FAIL with "cannot find module '../candidates'"

- [ ] **Step 3: Implement the candidate extractor**

Create `web/src/lib/edge-llm/candidates.ts`:

```typescript
/**
 * Rule-based candidate concept extractor.
 *
 * Over-generates likely concept phrases from a note chunk using simple
 * patterns: wiki-link targets, capitalised noun phrases, acronyms, and
 * hyphenated technical compounds. The LLM downstream filters this list
 * by index — that's how we keep the LLM output small and bounded.
 */

const WIKI_LINK_RE = /\[\[([^\[\]]+)\]\]/g;
const CAPITALISED_PHRASE_RE = /\b([A-Z][a-zA-Z]*(?:[ -][A-Z][a-zA-Z]*){0,3})\b/g;
const ACRONYM_RE = /\b([A-Z]{2,6})\b/g;
const HYPHENATED_RE = /\b([a-z]+(?:-[a-z]+){1,3})\b/g;

const MAX_CANDIDATES = 30;

const STOPWORDS = new Set([
  "The", "This", "That", "These", "Those", "It", "Is", "Are", "Was",
  "Were", "Be", "Been", "Being", "Has", "Have", "Had", "Do", "Does",
  "Did", "I", "You", "He", "She", "We", "They", "A", "An",
]);

function pushUnique(out: string[], seen: Set<string>, value: string): void {
  const trimmed = value.trim();
  if (trimmed.length < 2) return;
  if (STOPWORDS.has(trimmed)) return;
  const key = trimmed.toLowerCase();
  if (seen.has(key)) return;
  seen.add(key);
  out.push(trimmed);
}

export function extractCandidates(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();

  // 1. Wiki-link targets (highest priority — explicit user intent).
  for (const m of text.matchAll(WIKI_LINK_RE)) {
    pushUnique(out, seen, m[1]!);
    if (out.length >= MAX_CANDIDATES) return out;
  }

  // 2. Capitalised multi-word phrases (Proper Nouns, Title Case Topics).
  for (const m of text.matchAll(CAPITALISED_PHRASE_RE)) {
    pushUnique(out, seen, m[1]!);
    if (out.length >= MAX_CANDIDATES) return out;
  }

  // 3. Acronyms (JSON, HTML, ML).
  for (const m of text.matchAll(ACRONYM_RE)) {
    pushUnique(out, seen, m[1]!);
    if (out.length >= MAX_CANDIDATES) return out;
  }

  // 4. Hyphenated technical compounds (non-blocking, event-loop).
  for (const m of text.matchAll(HYPHENATED_RE)) {
    pushUnique(out, seen, m[1]!);
    if (out.length >= MAX_CANDIDATES) return out;
  }

  return out;
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/lib/edge-llm/__tests__/candidates.test.ts`
Expected: 7/7 pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/edge-llm/candidates.ts web/src/lib/edge-llm/__tests__/candidates.test.ts
git commit -m "edge-llm: rule-based candidate extractor

Over-generates concept candidates from a chunk using regex: wiki
links, capitalised phrases, acronyms, and hyphenated compounds.
Capped at 30 per chunk. The LLM downstream filters by index, so
this can be aggressive — false positives are cheap to drop."
```

---

## Task 4: Dedupe / canonicalize (pure function + tests)

**Files:**
- Create: `web/src/lib/edge-llm/dedupe.ts`
- Create: `web/src/lib/edge-llm/__tests__/dedupe.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/src/lib/edge-llm/__tests__/dedupe.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { canonicalizeConcepts, normalizeConceptKey } from "../dedupe";

describe("normalizeConceptKey", () => {
  it("lowercases", () => {
    expect(normalizeConceptKey("Machine Learning")).toBe("machine learning");
  });

  it("collapses whitespace", () => {
    expect(normalizeConceptKey("  multi   paradigm ")).toBe("multi paradigm");
  });

  it("strips trailing punctuation", () => {
    expect(normalizeConceptKey("JavaScript.")).toBe("javascript");
  });
});

describe("canonicalizeConcepts", () => {
  it("merges exact duplicates and unions sources", () => {
    const out = canonicalizeConcepts([
      { text: "JavaScript", confidence: 0.9, sources: [0] },
      { text: "javascript", confidence: 0.8, sources: [2] },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]!.text).toBe("JavaScript"); // first surface form wins on tie
    expect(out[0]!.confidence).toBe(0.9);
    expect(out[0]!.sources.sort()).toEqual([0, 2]);
  });

  it("merges substring matches keeping the longest surface form", () => {
    const out = canonicalizeConcepts([
      { text: "multi-paradigm", confidence: 0.9, sources: [0] },
      { text: "multi-paradigm programming", confidence: 0.8, sources: [1] },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]!.text).toBe("multi-paradigm programming");
  });

  it("does NOT merge unrelated concepts that happen to share a word", () => {
    const out = canonicalizeConcepts([
      { text: "machine learning", confidence: 0.9, sources: [0] },
      { text: "machine code", confidence: 0.8, sources: [1] },
    ]);
    expect(out).toHaveLength(2);
  });

  it("preserves max confidence among merged variants", () => {
    const out = canonicalizeConcepts([
      { text: "ML", confidence: 0.7, sources: [0] },
      { text: "ml", confidence: 0.95, sources: [1] },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]!.confidence).toBe(0.95);
  });

  it("returns empty array for empty input", () => {
    expect(canonicalizeConcepts([])).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/lib/edge-llm/__tests__/dedupe.test.ts`
Expected: FAIL with "cannot find module '../dedupe'"

- [ ] **Step 3: Implement dedupe**

Create `web/src/lib/edge-llm/dedupe.ts`:

```typescript
/**
 * Deterministic concept dedup / canonicalisation.
 *
 * Run after the LLM map step has produced concepts from each chunk.
 * Merges exact normalised duplicates and substring-matching variants
 * (e.g. "multi-paradigm" + "multi-paradigm programming" → keep the
 * longer one as canonical).
 *
 * No LLM, no embeddings — string operations only. Embeddings live
 * server-side and would require an extra round-trip; this catches
 * the dominant case (chunk overlap producing the same concept twice
 * or a slightly longer phrase in a different chunk).
 */

import type { CanonicalConcept } from "./types";

export function normalizeConceptKey(text: string): string {
  return text
    .toLowerCase()
    .replace(/[.!?,;:]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Merge `b` into `a`, returning the merged concept. */
function merge(a: CanonicalConcept, b: CanonicalConcept): CanonicalConcept {
  // Keep the longest surface form as canonical.
  const text = a.text.length >= b.text.length ? a.text : b.text;
  const confidence = Math.max(a.confidence, b.confidence);
  const sources = Array.from(new Set([...a.sources, ...b.sources])).sort(
    (x, y) => x - y,
  );
  return { text, confidence, sources };
}

/** Return true if `inner`'s normalised key is fully contained in `outer`'s. */
function isSubstring(inner: string, outer: string): boolean {
  // Word-boundary aware substring check: avoid "ml" matching "html".
  const innerKey = normalizeConceptKey(inner);
  const outerKey = normalizeConceptKey(outer);
  if (innerKey === outerKey) return true;
  if (innerKey.length < 3) return false; // too short to substring-match safely
  const re = new RegExp(`\\b${innerKey.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`);
  return re.test(outerKey);
}

export function canonicalizeConcepts(
  concepts: CanonicalConcept[],
): CanonicalConcept[] {
  if (concepts.length === 0) return [];

  // Sort longest-first so substring merges fold shorter into longer.
  const sorted = [...concepts].sort((a, b) => b.text.length - a.text.length);
  const out: CanonicalConcept[] = [];

  for (const c of sorted) {
    let merged = false;
    for (let i = 0; i < out.length; i++) {
      if (isSubstring(c.text, out[i]!.text)) {
        out[i] = merge(out[i]!, c);
        merged = true;
        break;
      }
    }
    if (!merged) out.push(c);
  }

  // Deterministic order: alphabetical by canonical key.
  return out.sort((a, b) =>
    normalizeConceptKey(a.text).localeCompare(normalizeConceptKey(b.text)),
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/lib/edge-llm/__tests__/dedupe.test.ts`
Expected: 7/7 pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/edge-llm/dedupe.ts web/src/lib/edge-llm/__tests__/dedupe.test.ts
git commit -m "edge-llm: deterministic concept dedup

Merges normalised exact duplicates and substring-matching variants.
Keeps the longest surface form, max confidence, union of source
chunk indices. Pure string ops — no LLM, no embeddings."
```

---

## Task 5: New schema and prompt for chunk extraction

**Files:**
- Modify: `web/src/lib/edge-llm/schemas.ts`
- Modify: `web/src/lib/edge-llm/prompts.ts`

- [ ] **Step 1: Replace EXTRACTION_SCHEMA with CHUNK_EXTRACTION_SCHEMA**

In `web/src/lib/edge-llm/schemas.ts`, replace the entire `EXTRACTION_SCHEMA` const with:

```typescript
/**
 * Schema for one chunk's LLM map step.
 *
 * Output is integer indices into the candidates array, NOT strings.
 * This bounds output size to roughly:
 *   - keep:  N integers (N ≤ ~30 candidates)
 *   - relations: 3-tuples of (int, enum string, int)
 *
 * Total well under 200 tokens regardless of note size.
 */
export const CHUNK_EXTRACTION_SCHEMA = {
  type: "object" as const,
  properties: {
    keep: {
      type: "array" as const,
      items: { type: "integer" as const, minimum: 0 },
    },
    relations: {
      type: "array" as const,
      items: {
        type: "array" as const,
        prefixItems: [
          { type: "integer" as const, minimum: 0 },
          {
            type: "string" as const,
            enum: [
              "IS_A",
              "PART_OF",
              "CAUSES",
              "CONTRASTS_WITH",
              "USES",
              "PRODUCES",
              "RELATED_TO",
            ],
          },
          { type: "integer" as const, minimum: 0 },
        ],
        minItems: 3,
        maxItems: 3,
      },
    },
  },
  required: ["keep", "relations"],
  additionalProperties: false,
};
```

Keep `META_SCHEMA` and `INSIGHT_SCHEMA` unchanged. Delete the now-unused `EXTRACTION_SCHEMA`.

- [ ] **Step 2: Replace the extraction prompt**

In `web/src/lib/edge-llm/prompts.ts`, replace `EXTRACTION_SYSTEM_PROMPT` and `buildExtractionPrompt` with:

```typescript
const CHUNK_EXTRACTION_SYSTEM_PROMPT = `You are filtering candidate concept phrases extracted from a note chunk.

You will receive:
- The chunk text
- A numbered list of CANDIDATES (rule-extracted noun phrases, may include false positives)
- A list of KNOWN concepts already in the user's knowledge base

Your job:
1. Pick which candidates are real, meaningful concepts. Output their indices in "keep".
2. List any clear semantic relations between kept concepts in "relations" as
   [sourceIdx, type, targetIdx] tuples.
   Use ONLY these relation types: IS_A, PART_OF, CAUSES, CONTRASTS_WITH, USES, PRODUCES, RELATED_TO.
3. Skip relations with the same source and target.
4. Be conservative — prefer fewer, high-quality picks over many noisy ones.

Return ONLY valid JSON in this shape, no markdown fences:
{ "keep": [<int>, ...], "relations": [[<int>, "<TYPE>", <int>], ...] }

KNOWN concepts (reuse where the candidate is a synonym): {known_csv}`;

/**
 * Build messages for the per-chunk LLM map step.
 *
 * Mirrors the GraphRAG/KGGen pattern: candidates over-generated by rules,
 * filtered by integer indices from the LLM. Output is bounded to ~150
 * tokens regardless of chunk size, eliminating the truncation failures
 * that plagued the one-shot extraction prompt.
 */
export function buildChunkExtractionPrompt(
  chunkText: string,
  candidates: string[],
  knownConcepts: string[],
): { system: string; user: string } {
  const knownCsv =
    knownConcepts.length > 0
      ? knownConcepts.slice(0, 100).join(", ")
      : "none yet";
  const system = CHUNK_EXTRACTION_SYSTEM_PROMPT.replace(
    "{known_csv}",
    knownCsv,
  );

  const numbered = candidates
    .map((c, i) => `${i}: ${c}`)
    .join("\n");
  const user = `CHUNK:\n${chunkText.slice(0, 1500)}\n\nCANDIDATES:\n${numbered}`;

  return { system, user };
}
```

Delete the old `EXTRACTION_SYSTEM_PROMPT` and `buildExtractionPrompt` exports. Keep `buildMetaPrompt` and `buildInsightPrompt` unchanged.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: errors in `inference-client.ts` (it still imports the old prompt/schema). That's expected — Task 6 fixes it.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/edge-llm/schemas.ts web/src/lib/edge-llm/prompts.ts
git commit -m "edge-llm: chunk-level schema + prompt

Replaces the one-shot EXTRACTION_SCHEMA (string concepts + relations)
with CHUNK_EXTRACTION_SCHEMA (integer indices into a candidates list).
Output is bounded to ~150 tokens per chunk regardless of note size,
eliminating mid-JSON truncation failures.

Note: this commit intentionally breaks inference-client.ts — fixed
in the next task (extractFromChunk replacement)."
```

---

## Task 6: Replace extractConcepts with extractFromChunk

**Files:**
- Modify: `web/src/lib/edge-llm/inference-client.ts`

- [ ] **Step 1: Replace extractConcepts with extractFromChunk**

In `web/src/lib/edge-llm/inference-client.ts`, replace the existing `extractConcepts` function (and its imports) with:

```typescript
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

  // Validate and filter to in-range indices.
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
```

Keep `classifyMeta` and `generateInsight` exactly as they are. Delete the old `extractConcepts` export.

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: errors in `edge-processing.ts` (it still calls `extractConcepts`). Fixed in next task.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/edge-llm/inference-client.ts
git commit -m "edge-llm: replace extractConcepts with per-chunk extractFromChunk

Output max_tokens dropped 1024 -> 256 because the model emits
integer indices into a candidates array, not full concept strings.
Includes index-range validation and self-loop filtering on the
parsed result."
```

---

## Task 7: Wire chunked pipeline into edge-processing

**Files:**
- Modify: `web/src/lib/orchestration/edge-processing.ts`

- [ ] **Step 1: Replace runEdgeProcessing implementation**

In `web/src/lib/orchestration/edge-processing.ts`, replace the entire file body (keep the docstring at top) with:

```typescript
/**
 * Edge LLM processing orchestration (chunked map-reduce pipeline).
 *
 * For each note:
 *   1. Chunk the (title + content) into ~500-char windows.
 *   2. Per chunk: rule-based candidate extraction → LLM filter by index → reducer input.
 *   3. After all chunks: dedupe across chunks → POST to /v1/extraction-results.
 *   4. Run meta-classification on the deduped concept list (synonym/subtopic).
 *
 * Each LLM call has bounded output (max_tokens=256), eliminating the mid-JSON
 * truncation that the previous one-shot extraction hit on long notes.
 */

import { extractFromChunk, classifyMeta } from "../edge-llm/inference-client";
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
  /** Optional progress callback: (chunkIdx, totalChunks) -> void */
  onProgress?: (done: number, total: number) => void;
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
      return { status: "completed", conceptCount: 0, relationCount: 0, chunksProcessed: 0 };
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

      for (const idx of result.keep) {
        const text = candidates[idx];
        if (!text) continue;
        allConcepts.push({
          text,
          confidence: 0.9,
          sources: [chunk.index],
        });
      }

      for (const [srcIdx, type, tgtIdx] of result.relations) {
        const source = candidates[srcIdx];
        const target = candidates[tgtIdx];
        if (!source || !target) continue;
        allRelations.push({ source, type, target });
      }
    }

    // Reduce: dedupe concepts, then re-map relations to canonical surfaces.
    const canonical = canonicalizeConcepts(allConcepts);
    const canonicalKeys = new Map<string, string>(); // normalised -> canonical text
    for (const c of canonical) {
      // Map every variant we saw back to its canonical text.
      canonicalKeys.set(c.text.toLowerCase().trim(), c.text);
    }

    // For relations, look up endpoints by case-insensitive match into canonical list.
    const validRelations: Array<{
      source: string;
      type: string;
      target: string;
      confidence: number;
    }> = [];
    const findCanonical = (text: string): string | null => {
      const key = text.toLowerCase().trim();
      // Direct hit
      if (canonicalKeys.has(key)) return canonicalKeys.get(key)!;
      // Substring fallback: any canonical contains the relation text or vice versa
      for (const c of canonical) {
        const ckey = c.text.toLowerCase();
        if (ckey.includes(key) || key.includes(ckey)) return c.text;
      }
      return null;
    };

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

    await submitExtractionResults(request.baseUrl, {
      note_id: request.noteId,
      content_hash: request.contentHash,
      concepts: finalConcepts,
      relations: validRelations,
      summary: "",
    });

    // Meta-classification (synonym/subtopic) on the deduped concept list.
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: clean (the only consumer of the old `extractConcepts` was this file).

- [ ] **Step 3: Run all frontend tests**

Run: `cd web && npx vitest run`
Expected: all 158 existing tests pass + the 19 new chunker/candidates/dedupe tests = 177 total.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/orchestration/edge-processing.ts
git commit -m "edge-processing: chunked map-reduce pipeline

Replaces the one-shot LLM extraction with:
  1. chunkNote -> windows
  2. per chunk: extractCandidates (rules) + extractFromChunk (LLM, indices)
  3. canonicalizeConcepts (string-only dedup)
  4. submitExtractionResults + classifyMeta as before

Each LLM call output is bounded to ~150 tokens. The orchestrator
exposes onProgress so the UI can show 'chunk N of M' during edits."
```

---

## Task 8: Surface chunk progress in the UI

**Files:**
- Modify: `web/src/components/editor/NoteEditor.tsx`

- [ ] **Step 1: Pass an onProgress callback into runEdgeProcessing**

In `web/src/components/editor/NoteEditor.tsx`, find the `startProcessing` callback's edge-mode branch (around line 484) and update the runEdgeProcessing call:

Find:
```typescript
const result = await runEdgeProcessing({
  baseUrl,
  noteId,
  noteTitle: snapshot.noteTitle.trim() || "Untitled",
  contentText: snapshot.plainText,
  contentHash,
});
```

Replace with:
```typescript
const result = await runEdgeProcessing({
  baseUrl,
  noteId,
  noteTitle: snapshot.noteTitle.trim() || "Untitled",
  contentText: snapshot.plainText,
  contentHash,
  onProgress: (done, total) => {
    setProcessStatus(
      total > 1 ? (`running` as const) : ("running" as const),
    );
    // Console signal for debugging — UI shows "running" generically.
    console.info(`[edge-llm] chunk ${done}/${total}`);
  },
});
```

(The status string stays "running" — adding a richer "running 3/6" status would require changes to the ProcessStatus type and toolbar; out of scope for this plan.)

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/editor/NoteEditor.tsx
git commit -m "edge-processing: log per-chunk progress

Wires runEdgeProcessing's onProgress callback to console.info so
'chunk N of M' appears in DevTools during note editing. Status
badge stays 'running' across all chunks (no UI change beyond logs)."
```

---

## Task 9: End-to-end verification against the running stack

**Files:** none modified.

- [ ] **Step 1: Restart the API + web containers to pick up edits**

Run:
```bash
docker compose -f infra/docker-compose.yml restart web
sleep 15
```

(API doesn't need a restart — only the frontend changed.)

- [ ] **Step 2: Open the app in the browser and edit a long note**

In the browser at `http://localhost:3000`:
1. Open a long existing note (e.g. JavaScript study notes, ~3000 chars).
2. Make a small edit and wait for the processing badge.
3. Open DevTools → Console and confirm logs of the form:

```
[edge-llm] extractFromChunk: starting {chunkIdx: 0, candidates: 12, ...}
[edge-llm] extractFromChunk: done {chunkIdx: 0, elapsedSeconds: "3.4", ...}
[edge-llm] chunk 1/6
[edge-llm] extractFromChunk: starting {chunkIdx: 1, ...}
...
```

Expected: no `JSON parse failed` errors. Final result is a small set of
canonical concepts (likely 5-12) and relations.

- [ ] **Step 3: Verify the concepts landed in the tenant schema**

Run:
```bash
USER_SCHEMA=$(curl -s -X POST http://localhost:8000/v1/auth/dev/login -c /tmp/nn_v.txt 2>/dev/null > /dev/null && curl -s -b /tmp/nn_v.txt http://localhost:8000/v1/auth/me | python3 -c "import sys,json;print(json.load(sys.stdin)['schema_name'])")
docker compose -f infra/docker-compose.yml exec db psql -U neuronote -d neuronote -c "SELECT concept_text FROM ${USER_SCHEMA}.concept_registry ORDER BY created_at DESC LIMIT 20"
```

Expected: a list of canonical concepts from the edited note, no obvious junk
duplicates ("multi-paradigm" should NOT appear alongside "multi-paradigm
programming" — only the longer form).

- [ ] **Step 4: Test on a SHORT note to confirm single-chunk path still works**

In the browser, create a new note with ~50 chars of content (e.g. "REST APIs are stateless"). Wait for processing. DevTools should show exactly one `extractFromChunk` call (chunkIdx: 0) and complete in <5 seconds.

- [ ] **Step 5: Confirm the badge transitions to 'completed'**

In the editor, after processing finishes the toolbar badge should turn from "running" → "completed". The graph view should show the new entity nodes. If the badge sticks at "running" for >60 seconds on a 3000-char note, capture the DevTools console output and treat it as a regression.

- [ ] **Step 6: Final commit (only if any cleanup needed)**

If the verification turned up cosmetic issues (extra console logs, dead code from the prior `extractConcepts` etc.), clean up and commit. Otherwise, no commit needed for this task.

---

## Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| LLM returns indices out of range | `extractFromChunk` filters them; out-of-range entries silently dropped. |
| Two relations endpoints don't match any canonical concept | `findCanonical` returns null → relation dropped. |
| Substring dedup accidentally merges unrelated concepts (e.g. "Java" inside "JavaScript") | Word-boundary regex in `isSubstring` prevents this. Tests cover the case. |
| Long note (e.g. 10K chars) takes too long | At ~5s/chunk × 20 chunks = 100s. Beyond the 30-60s budget. Acceptable for now; can add a max-chunks cap later. |
| Llama 3.2 3B ignores the integer-only schema and emits strings | Schema-constrained decoding rejects this at the grammar level; if it slips through, JSON.parse may succeed but the `typeof n === "number"` filter will drop everything. Net effect: empty `keep` from that chunk, processing continues. |

## What this plan does NOT do (out of scope)

- Embedding-based dedup (server-side embeddings would require an extra round-trip). String + substring dedup catches the dominant cases.
- Server-side summary generation. We pass `summary: ""` for now; can be added as a final LLM call after reduce if needed.
- A "running 3/6" status string in the toolbar (would require a new ProcessStatus variant + UI).
- Embedding the candidate extractor in a Web Worker (current candidate extractor is fast enough on the main thread for note-sized inputs).
