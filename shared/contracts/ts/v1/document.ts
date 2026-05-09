/**
 * TipTap document block-attrs contract (v1).
 *
 * Mirror of shared/contracts/python/v1/document.py. Both files must
 * stay in sync — change one, change the other in the same commit.
 */

export interface TipTapBlockAttrs {
  blockUid: string;
  parentBlockUid?: string | null;
  indentLevel?: number | null;
  level?: number | null;
  // Tolerates additional editor-only fields.
  [extra: string]: unknown;
}

export const STRUCTURAL_BLOCK_TYPES: readonly string[] = [
  "paragraph",
  "heading",
  "blockquote",
  "codeBlock",
  "horizontalRule",
  "bulletList",
  "orderedList",
  "listItem",
  "taskList",
  "taskItem",
  "mathBlock",
  "image",
  "blockRef",
] as const;
