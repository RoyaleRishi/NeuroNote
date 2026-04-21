/**
 * Prompt templates for edge LLM inference.
 *
 * Ported verbatim from the Python backend:
 * - slm_extractor.py (extraction)
 * - concept_meta.py (meta-classification)
 * - concept_insight_service.py (insight generation)
 */

// -- Extraction prompts (from api/src/app/nlp/slm_extractor.py) -------------

const EXTRACTION_SYSTEM_PROMPT = `You are a knowledge graph extraction engine. Extract from the given note:
1. concepts — the key ideas, entities, and topics, each in canonical lowercase form
   (expand acronyms: "ML" → "machine learning"; prefer singular form; reuse names from the known list)
2. relations — typed semantic relations between concepts using ONLY these relation types:
   IS_A, PART_OF, CAUSES, CONTRASTS_WITH, USES, PRODUCES, RELATED_TO
3. summary — one sentence capturing the note's main idea

Return ONLY valid JSON matching this schema — no markdown fences, no extra keys:
{
  "concepts": [{"text": "<string>", "confidence": <0.0-1.0>}],
  "relations": [{"source": "<string>", "type": "<RELATION_TYPE>", "target": "<string>", "confidence": <0.0-1.0>}],
  "summary": "<string>"
}

Known concepts already in the knowledge base (reuse these exact forms where applicable):
{known_concepts_csv}`;

/**
 * Build system and user messages for concept/relation extraction.
 *
 * Mirrors `SLMExtractor.extract()` in `slm_extractor.py`.
 */
export function buildExtractionPrompt(
  title: string,
  content: string,
  knownConcepts: string[],
): { system: string; user: string } {
  const knownCsv =
    knownConcepts.length > 0
      ? knownConcepts.slice(0, 200).join(", ")
      : "none yet";

  const system = EXTRACTION_SYSTEM_PROMPT.replace(
    "{known_concepts_csv}",
    knownCsv,
  );
  const user = `Title: ${title || "(untitled)"}\nContent: ${content.slice(0, 4000)}`;

  return { system, user };
}

// -- Meta-classification prompts (from api/src/app/nlp/concept_meta.py) -----

const META_SYSTEM_PROMPT = `You are a concept taxonomy assistant. Given a list of concepts from a personal \
knowledge base, identify relationships between them.

1. synonym_pairs — concepts that refer to the same idea (abbreviations, aliases, \
different phrasings). Example: "ML" and "machine learning"
2. subtopic_pairs — directed: "specific" is a specialisation of "broader". \
Example: "backpropagation" is a subtopic of "neural networks"

Rules:
- Only pair concepts from the provided list. Do not introduce outside concepts.
- Be conservative — only emit pairs you are highly confident about.
- synonym_pairs are symmetric (order does not matter).

Respond ONLY with valid JSON, no markdown fences:
{
  "synonym_pairs": [{"a": "...", "b": "..."}],
  "subtopic_pairs": [{"specific": "...", "broader": "..."}]
}`;

/**
 * Build system and user messages for meta-classification of concept pairs.
 *
 * Mirrors `ConceptMetaClassifier.classify()` in `concept_meta.py`.
 */
export function buildMetaPrompt(concepts: string[]): {
  system: string;
  user: string;
} {
  const system = META_SYSTEM_PROMPT;
  const user =
    "Concepts:\n" + concepts.map((c) => `- ${c}`).join("\n");

  return { system, user };
}

// -- Insight prompts (from api/src/app/services/concept_insight_service.py) --

const INSIGHT_SYSTEM_PROMPT = `You are a knowledge synthesis assistant. Generate an insight about a concept based \
SOLELY on the user's own notes.

Rules:
- The insight must draw only from the provided notes. Do not add external knowledge.
- Reference note titles explicitly, e.g. "In your note 'Title'...".
- Keep the insight to 2–3 focused paragraphs.
- For learning_links: suggest 3–4 genuinely reputable URLs (Wikipedia, official \
documentation, well-known academic sources). Use only real, widely-known URLs.

Respond ONLY with valid JSON in exactly this shape (no markdown fences):
{
  "insight": "...",
  "learning_links": [
    {"title": "...", "url": "https://...", "description": "..."}
  ]
}`;

/** Max chars of content passed to LLM per note context. */
const MAX_CONTENT_PER_NOTE = 600;

/**
 * Build system and user messages for concept insight generation.
 *
 * Mirrors `ConceptInsightService._call_llm()` in `concept_insight_service.py`.
 */
export function buildInsightPrompt(
  conceptLabel: string,
  noteContexts: Array<{ title: string; excerpt: string }>,
): { system: string; user: string } {
  const system = INSIGHT_SYSTEM_PROMPT;

  const parts = noteContexts.map(
    (note, i) =>
      `[Note ${i + 1}: '${note.title}']\n${note.excerpt.slice(0, MAX_CONTENT_PER_NOTE)}`,
  );
  const context = parts.join("\n\n---\n\n");

  const user = `Concept to analyse: "${conceptLabel}"\n\nUser notes mentioning this concept:\n\n${context}`;

  return { system, user };
}
