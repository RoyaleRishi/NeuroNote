import { describe, expect, it } from "vitest";
import { getTagColorClass, TAG_CHIP_CLASSES } from "./tag-colors";

describe("tag-colors", () => {
  it("returns one of the eight tag-chip classes", () => {
    const cls = getTagColorClass("javascript");
    expect(TAG_CHIP_CLASSES).toContain(cls);
  });

  it("is deterministic — same tag → same class", () => {
    expect(getTagColorClass("javascript")).toBe(getTagColorClass("javascript"));
  });

  it("distributes across classes — 100 distinct tags hit at least 5 buckets", () => {
    const seen = new Set<string>();
    for (let i = 0; i < 100; i++) seen.add(getTagColorClass(`tag-${i}`));
    expect(seen.size).toBeGreaterThan(4);
  });
});
