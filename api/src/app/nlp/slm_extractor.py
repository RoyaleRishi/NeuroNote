"""LLM-based concept and relation extractor (index-filter mode).

Accepts pre-generated rule-based candidates and asks the LLM to filter
by index — never free-generates concept text. This makes output bounded,
fast, and far more deterministic than free-generation.

Returns None on any failure so the pipeline falls back to rule-based extraction.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.nlp.llm_client import LLMClient

_LOGGER = logging.getLogger(__name__)

_RELATION_TYPES = frozenset(
    {"IS_A", "PART_OF", "CAUSES", "CONTRASTS_WITH", "USES", "PRODUCES", "RELATED_TO"}
)

_SYSTEM_PROMPT = """You are filtering candidate concept phrases extracted from a note.

You will receive:
- The note text (title + content)
- A numbered list of CANDIDATES (rule-extracted phrases, may include false positives)
- A list of KNOWN concepts already in the user's knowledge base

Your job:
1. Pick which candidates are real, meaningful concepts. Output their indices in "keep".
2. List any clear semantic relations between kept candidates as [srcIdx, type, tgtIdx] triples.
   Use ONLY these relation types: IS_A, PART_OF, CAUSES, CONTRASTS_WITH, USES, PRODUCES, RELATED_TO.
3. Write a one-sentence summary of the note in "summary".
4. Be conservative — prefer fewer, high-quality picks over many noisy ones.
5. Skip relations where sourceIdx equals targetIdx.

Return ONLY valid JSON in this shape, no markdown fences:
{{"keep": [<int>, ...], "relations": [[<int>, "<TYPE>", <int>], ...], "summary": "<string>"}}

Known concepts (reuse where a candidate is a synonym): {known_concepts_csv}"""

_USER_TEMPLATE = "Title: {title}\nContent: {content}\n\nCANDIDATES:\n{numbered}"


@dataclass(slots=True)
class SLMConcept:
    text: str
    confidence: float


@dataclass(slots=True)
class SLMRelation:
    source: str
    type: str
    target: str
    confidence: float


@dataclass(slots=True)
class SLMExtractionResult:
    concepts: list[SLMConcept]
    relations: list[SLMRelation]
    summary: str


def _parse_index_result(raw: str, candidates: list[str]) -> SLMExtractionResult | None:
    """Parse the LLM's index-based JSON response into a typed result.

    Returns None if JSON is invalid or top-level structure is not a dict.
    Out-of-bounds indices and unknown relation types are silently dropped.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _LOGGER.warning("SLM response is not valid JSON: %s", exc)
        return None

    if not isinstance(data, dict):
        return None

    max_idx = len(candidates)
    keep_raw = data.get("keep") or []
    if not isinstance(keep_raw, list):
        return None

    keep_indices = [
        i for i in keep_raw
        if isinstance(i, int) and 0 <= i < max_idx
    ]

    concepts = [
        SLMConcept(text=candidates[i].lower(), confidence=0.9)
        for i in keep_indices
    ]

    relations: list[SLMRelation] = []
    for item in data.get("relations") or []:
        if not isinstance(item, list) or len(item) != 3:
            continue
        src_raw, type_raw, tgt_raw = item
        if not isinstance(src_raw, int) or not isinstance(tgt_raw, int):
            continue
        if src_raw < 0 or src_raw >= max_idx or tgt_raw < 0 or tgt_raw >= max_idx:
            continue
        if src_raw == tgt_raw:
            continue
        rel_type = str(type_raw).strip().upper()
        if rel_type not in _RELATION_TYPES:
            continue
        relations.append(SLMRelation(
            source=candidates[src_raw].lower(),
            type=rel_type,
            target=candidates[tgt_raw].lower(),
            confidence=0.85,
        ))

    summary = str(data.get("summary", "")).strip()
    return SLMExtractionResult(concepts=concepts, relations=relations, summary=summary)


class SLMExtractor:
    """Filters rule-generated concept candidates using an LLM."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_ms: int = 8000,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_s = timeout_ms / 1000.0

    def extract(
        self,
        *,
        title: str,
        preprocessed_content: str,
        candidates: list[str],
        known_concepts: list[str],
    ) -> SLMExtractionResult | None:
        """Filter candidates by index using the LLM.

        Returns None on any error so the caller can fall back to rule-based extraction.
        """
        if not candidates:
            return SLMExtractionResult(concepts=[], relations=[], summary="")

        known_csv = ", ".join(known_concepts[:200]) if known_concepts else "none yet"
        system = _SYSTEM_PROMPT.format(known_concepts_csv=known_csv)
        numbered = "\n".join(f"{i}: {c}" for i, c in enumerate(candidates))
        user = _USER_TEMPLATE.format(
            title=title or "(untitled)",
            content=preprocessed_content[:4000],
            numbered=numbered,
        )

        raw = LLMClient(
            api_key=self._api_key,
            model=self._model,
            base_url=self._base_url,
            timeout_s=self._timeout_s,
        ).complete(system=system, user=user, max_tokens=512)

        if not raw:
            _LOGGER.warning("LLM returned empty response; falling back to rule-based")
            return None

        _LOGGER.debug("LLM raw response (%d chars): %s", len(raw), raw[:200])

        # Strip markdown code fences if the model wrapped the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        return _parse_index_result(raw, candidates)


__all__ = ["SLMConcept", "SLMRelation", "SLMExtractionResult", "SLMExtractor", "_parse_index_result"]
