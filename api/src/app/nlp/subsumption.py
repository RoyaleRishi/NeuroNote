"""Within-note lexical subsumption: variant merge + compound IS_A hierarchy.

Two deterministic, model-free operations over the salient concept set, both keyed
on each concept's **spaCy lemma** (captured in ``extraction.py``) rather than any
hand-rolled singularisation:

1. **Inflectional variant merge.** "neural network" and "neural networks" share
   the lemma key "neural network" and collapse to one concept node. spaCy's
   lemmatiser handles the full English inflection paradigm (including irregulars
   like "analyses"→"analysis"), so there is no plural-stripping rule to maintain.

2. **Compound head-modifier subsumption.** By the head-modifier principle of
   endocentric noun compounds, removing a leading modifier yields a hypernym:
   "deep neural network" is-a "neural network" is-a "network". We walk each
   concept's lemma-token suffixes (longest first) and link it to the *nearest*
   suffix that survived as a concept, emitting an ``IsAEdge`` (child = the more
   specific phrase, parent = the more general suffix). Display surfaces are
   preserved; only the matching key is the lemma.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.nlp.extraction import ConceptSpan


def _lemma_key(span: ConceptSpan) -> str:
    """Normalisation key for a concept: its spaCy lemma (fallback: lowercased text)."""
    return (span.lemma or span.text.lower()).strip()


@dataclass(frozen=True, slots=True)
class IsAEdge:
    """A semantic hyponymy edge: ``child`` is-a ``parent`` (child is more specific)."""

    child: str
    parent: str


@dataclass(frozen=True, slots=True)
class SubsumptionResult:
    concepts: list[ConceptSpan]
    is_a_edges: list[IsAEdge]


def merge_and_subsume(spans: list[ConceptSpan]) -> SubsumptionResult:
    """Collapse inflectional variants and derive compound IS_A edges."""
    if not spans:
        return SubsumptionResult(concepts=[], is_a_edges=[])

    # 1. Variant merge — one representative surface per lemma key. Prefer the
    #    higher-confidence span; break ties toward the shorter (cleaner) surface.
    best: dict[str, ConceptSpan] = {}
    order: list[str] = []
    for span in spans:
        key = _lemma_key(span)
        if not key:
            continue
        current = best.get(key)
        if current is None:
            best[key] = span
            order.append(key)
        elif (span.confidence, -len(span.text)) > (current.confidence, -len(current.text)):
            best[key] = span

    concepts = [best[key] for key in order]
    present = {key: best[key].text for key in best}  # lemma key -> display surface

    # 2. Compound subsumption — link each concept to its nearest existing suffix.
    edges: set[IsAEdge] = set()
    for key, span in best.items():
        tokens = key.split()
        if len(tokens) < 2:
            continue
        for start in range(1, len(tokens)):
            suffix = " ".join(tokens[start:])
            parent_surface = present.get(suffix)
            if parent_surface is not None and parent_surface.lower() != span.text.lower():
                edges.add(IsAEdge(child=span.text, parent=parent_surface))
                break  # nearest suffix only — preserves a clean chain

    sorted_edges = sorted(edges, key=lambda e: (e.child.lower(), e.parent.lower()))
    return SubsumptionResult(concepts=concepts, is_a_edges=sorted_edges)


__all__ = ["IsAEdge", "SubsumptionResult", "merge_and_subsume"]
