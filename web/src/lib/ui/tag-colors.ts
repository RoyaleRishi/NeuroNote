export const TAG_CHIP_CLASSES = [
  "tag-chip-blue",
  "tag-chip-green",
  "tag-chip-amber",
  "tag-chip-pink",
  "tag-chip-purple",
  "tag-chip-red",
  "tag-chip-sky",
  "tag-chip-violet",
] as const;

export type TagChipClass = (typeof TAG_CHIP_CLASSES)[number];

/**
 * Deterministic per-tag color class.  Hash the tag name into one of the
 * eight `.tag-chip-*` modifier classes defined in globals.css.  Stable
 * across reloads and machines so a given tag always renders the same color.
 */
export function getTagColorClass(tag: string): TagChipClass {
  let hash = 0;
  for (const c of tag) hash = (hash * 31 + c.charCodeAt(0)) | 0;
  return TAG_CHIP_CLASSES[Math.abs(hash) % TAG_CHIP_CLASSES.length]!;
}
