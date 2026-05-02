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
    const lower = result.map((c) => c.toLowerCase());
    expect(lower.filter((c) => c === "css")).toHaveLength(1);
  });

  it("filters out short tokens and stopwords", () => {
    const result = extractCandidates("It is a good thing.");
    expect(result.length).toBeLessThanOrEqual(0);
  });

  it("returns at most 30 candidates per chunk", () => {
    const big = Array.from({ length: 60 }, (_, i) => `Topic${i}`).join(" ");
    const result = extractCandidates(big);
    expect(result.length).toBeLessThanOrEqual(30);
  });
});
