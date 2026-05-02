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
