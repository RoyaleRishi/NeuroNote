import { describe, it, expect } from "vitest";
import { makeNewNoteId, nextUntitledTitle } from "./note-id";

describe("makeNewNoteId", () => {
  it("returns a string starting with 'note-'", () => {
    const id = makeNewNoteId();
    expect(id).toMatch(/^note-/);
  });

  it("matches expected format: note-{timestamp}-{random}", () => {
    const id = makeNewNoteId();
    expect(id).toMatch(/^note-\d+-\d+$/);
  });

  it("generates mostly unique ids across calls", () => {
    const ids = new Set(Array.from({ length: 20 }, () => makeNewNoteId()));
    // Timestamp-based with random suffix — occasional collisions within same ms are acceptable
    expect(ids.size).toBeGreaterThanOrEqual(18);
  });
});

describe("nextUntitledTitle", () => {
  it("returns 'Untitled' when no untitled note exists", () => {
    expect(nextUntitledTitle([])).toBe("Untitled");
    expect(nextUntitledTitle(["JS", "C programming"])).toBe("Untitled");
  });

  it("returns 'Untitled 2' when 'Untitled' is taken (case- and space-insensitive)", () => {
    expect(nextUntitledTitle(["Untitled"])).toBe("Untitled 2");
    expect(nextUntitledTitle(["  untitled "])).toBe("Untitled 2");
  });

  it("skips to the next free number across a run of untitled notes", () => {
    expect(nextUntitledTitle(["Untitled", "Untitled 2", "Untitled 3"])).toBe("Untitled 4");
  });

  it("fills the lowest available gap", () => {
    expect(nextUntitledTitle(["Untitled", "Untitled 3"])).toBe("Untitled 2");
  });
});
