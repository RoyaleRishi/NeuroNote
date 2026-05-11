"""Note content preprocessor — strips code and markup before NLP candidate extraction."""
from __future__ import annotations

import re

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_WHITESPACE_RE = re.compile(r"\s+")


def preprocess_content(raw: str) -> str:
    """Strip code fences, inline code, and markdown syntax from note content."""
    text = _FENCED_CODE_RE.sub(" ", raw)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _IMAGE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


__all__ = ["preprocess_content"]
