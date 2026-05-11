/**
 * JSON schemas for WebLLM constrained decoding.
 *
 * Used with `response_format: { type: "json_object", schema: ... }` to ensure
 * the model output matches the expected structure.
 */

/** Schema for one-sentence note summary output. */
export const SUMMARY_SCHEMA = {
  type: "object" as const,
  properties: {
    summary: { type: "string" as const },
  },
  required: ["summary"],
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
