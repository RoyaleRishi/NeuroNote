/**
 * JSON schemas for WebLLM constrained decoding.
 *
 * Used with `response_format: { type: "json_object", schema: ... }` to ensure
 * the model output matches the expected structure.
 */

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

/** Schema for meta-classification (synonym/subtopic pairs) output. */
export const META_SCHEMA = {
  type: "object" as const,
  properties: {
    synonym_pairs: {
      type: "array" as const,
      items: {
        type: "object" as const,
        properties: {
          a: { type: "string" as const },
          b: { type: "string" as const },
        },
        required: ["a", "b"],
        additionalProperties: false,
      },
    },
    subtopic_pairs: {
      type: "array" as const,
      items: {
        type: "object" as const,
        properties: {
          specific: { type: "string" as const },
          broader: { type: "string" as const },
        },
        required: ["specific", "broader"],
        additionalProperties: false,
      },
    },
  },
  required: ["synonym_pairs", "subtopic_pairs"],
  additionalProperties: false,
};

/** Schema for concept insight generation output. */
export const INSIGHT_SCHEMA = {
  type: "object" as const,
  properties: {
    insight: { type: "string" as const },
    learning_links: {
      type: "array" as const,
      items: {
        type: "object" as const,
        properties: {
          title: { type: "string" as const },
          url: { type: "string" as const },
          description: { type: "string" as const },
        },
        required: ["title", "url", "description"],
        additionalProperties: false,
      },
    },
  },
  required: ["insight", "learning_links"],
  additionalProperties: false,
};
