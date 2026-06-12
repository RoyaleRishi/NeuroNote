"""Shared text normalisation utilities.

Extracted from LocalGraphService, GlobalGraphService, and NoteRepository to
eliminate duplication and provide a single source of truth for title
normalisation, wiki-link extraction, entity key generation, and graph
include-type validation.
"""
from __future__ import annotations

import re

_WIKI_LINK_PATTERN = re.compile(r"\[\[([^\[\]]+)\]\]")
_VALID_INCLUDE_TYPES = {"note", "entity", "relation"}


def collapse_whitespace(value: str) -> str:
    """Collapse internal runs of whitespace into single spaces and strip the ends."""
    return " ".join(value.split())


def normalize_title(value: str) -> str:
    """Collapse whitespace and strip a title string."""
    return collapse_whitespace(value)


def normalize_title_key(value: str) -> str:
    """Collapse whitespace, strip, and lowercase — for case-insensitive comparison."""
    return normalize_title(value).lower()


def extract_wiki_link_titles(content_text: str) -> list[str]:
    """Return deduplicated, normalised wiki-link targets from ``[[Title]]`` syntax."""
    links: list[str] = []
    seen: set[str] = set()
    for match in _WIKI_LINK_PATTERN.finditer(content_text):
        normalized = normalize_title_key(match.group(1))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
    return links


def normalize_entity_key(value: str) -> str:
    """Slugify a value into a lowercase alphanumeric-dash key."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "unknown"


def normalize_include_types(values: list[str]) -> list[str]:
    """Validate and deduplicate graph include_types; return defaults when empty."""
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        cleaned = item.strip().lower()
        if cleaned not in _VALID_INCLUDE_TYPES or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    if not normalized:
        return ["note", "entity", "relation"]
    return normalized
