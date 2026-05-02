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
  const text = a.text.length >= b.text.length ? a.text : b.text;
  const confidence = Math.max(a.confidence, b.confidence);
  const sources = Array.from(new Set([...a.sources, ...b.sources])).sort(
    (x, y) => x - y,
  );
  return { text, confidence, sources };
}

/** Word-boundary aware: "ml" inside "html" should NOT match. */
function isSubstring(inner: string, outer: string): boolean {
  const innerKey = normalizeConceptKey(inner);
  const outerKey = normalizeConceptKey(outer);
  if (innerKey === outerKey) return true;
  if (innerKey.length < 3) return false;
  const re = new RegExp(`\\b${innerKey.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`);
  return re.test(outerKey);
}

export function canonicalizeConcepts(
  concepts: CanonicalConcept[],
): CanonicalConcept[] {
  if (concepts.length === 0) return [];

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

  return out.sort((a, b) =>
    normalizeConceptKey(a.text).localeCompare(normalizeConceptKey(b.text)),
  );
}
