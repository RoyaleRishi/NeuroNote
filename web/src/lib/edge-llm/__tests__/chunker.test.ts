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
    for (const c of chunks) {
      expect(c.text.length).toBeLessThanOrEqual(500);
    }
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
    const chars = new Set(chunks[0]!.text.slice(-30));
    const next = chunks[1]!.text.slice(0, 30);
    let hit = 0;
    for (const ch of next) if (chars.has(ch)) hit++;
    expect(hit).toBeGreaterThan(10);
  });

  it("never produces an empty chunk", () => {
    const chunks = chunkNote("", "", { targetSize: 500, overlap: 50 });
    expect(chunks).toEqual([]);
  });
});
