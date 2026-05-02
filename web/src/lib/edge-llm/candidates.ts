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

  // 2. Capitalised multi-word phrases.
  for (const m of text.matchAll(CAPITALISED_PHRASE_RE)) {
    pushUnique(out, seen, m[1]!);
    if (out.length >= MAX_CANDIDATES) return out;
  }

  // 3. Acronyms.
  for (const m of text.matchAll(ACRONYM_RE)) {
    pushUnique(out, seen, m[1]!);
    if (out.length >= MAX_CANDIDATES) return out;
  }

  // 4. Hyphenated technical compounds.
  for (const m of text.matchAll(HYPHENATED_RE)) {
    pushUnique(out, seen, m[1]!);
    if (out.length >= MAX_CANDIDATES) return out;
  }

  return out;
}
