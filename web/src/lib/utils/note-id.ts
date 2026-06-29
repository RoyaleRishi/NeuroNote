/** Generate a unique note ID in the format `note-{timestamp}-{random}`. */
export function makeNewNoteId(): string {
  return `note-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

/**
 * Pick a default title for a new note that won't collide with an existing one.
 *
 * Note titles are unique per tenant (the backend rejects duplicates with a 409
 * so `[[wiki links]]` resolve unambiguously). A new note defaults to "Untitled",
 * so the second blank note would otherwise fail to save. This returns the first
 * free name in the sequence "Untitled", "Untitled 2", "Untitled 3", … comparing
 * case- and surrounding-whitespace-insensitively to match backend normalisation.
 */
export function nextUntitledTitle(existingTitles: string[]): string {
  const base = "Untitled";
  const taken = new Set(existingTitles.map((title) => title.trim().toLowerCase()));
  if (!taken.has(base.toLowerCase())) {
    return base;
  }
  let n = 2;
  while (taken.has(`${base} ${n}`.toLowerCase())) {
    n += 1;
  }
  return `${base} ${n}`;
}
