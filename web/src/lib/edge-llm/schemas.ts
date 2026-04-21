/**
 * JSON schemas for WebLLM constrained decoding.
 *
 * Used with `response_format: { type: "json_object", schema: ... }` to ensure
 * the model output matches the expected structure.
 */

/** Schema for concept/relation extraction output. */
export const EXTRACTION_SCHEMA = {
  type: "object" as const,
  properties: {
    concepts: {
      type: "array" as const,
      items: {
        type: "object" as const,
        properties: {
          text: { type: "string" as const },
          confidence: { type: "number" as const, minimum: 0, maximum: 1 },
        },
        required: ["text", "confidence"],
        additionalProperties: false,
      },
    },
    relations: {
      type: "array" as const,
      items: {
        type: "object" as const,
        properties: {
          source: { type: "string" as const },
          type: {
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
          target: { type: "string" as const },
          confidence: { type: "number" as const, minimum: 0, maximum: 1 },
        },
        required: ["source", "type", "target", "confidence"],
        additionalProperties: false,
      },
    },
    summary: { type: "string" as const },
  },
  required: ["concepts", "relations", "summary"],
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
