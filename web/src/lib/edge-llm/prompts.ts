/**
 * Prompt templates for edge LLM inference.
 *
 * Adapted from the Python backend:
 * - concept_insight_service.py (insight generation)
 *
 * The summary prompt is browser-only (run after deterministic server-side
 * extraction completes).
 */

// -- Summary prompt (one-sentence note summary, run after dedup) -------------

const SUMMARY_SYSTEM_PROMPT = `You write a single-sentence summary of a note for use in a knowledge graph.

Rules:
- Exactly one sentence, max 25 words.
- Capture the central topic, not a comprehensive description.
- No preamble like "This note is about...". Just the summary.
- Reference 1-2 of the key concepts when natural.

Return ONLY valid JSON, no markdown fences:
{ "summary": "<one sentence>" }`;

/**
 * Build messages for the summary step.
 *
 * Runs once after canonical concepts are known. Bounded output (~100 tokens)
 * keeps it safely under the model's budget.
 */
export function buildSummaryPrompt(
  title: string,
  content: string,
  concepts: string[],
): { system: string; user: string } {
  const conceptList =
    concepts.length > 0 ? concepts.slice(0, 12).join(", ") : "(none)";
  // Cap content to keep prefill cost predictable on long notes.
  const trimmedContent = content.length > 1500
    ? content.slice(0, 1500) + "..."
    : content;
  const user = `Title: ${title || "(untitled)"}
Key concepts: ${conceptList}

Content:
${trimmedContent}`;
  return { system: SUMMARY_SYSTEM_PROMPT, user };
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
