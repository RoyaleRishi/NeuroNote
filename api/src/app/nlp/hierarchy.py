"""Deterministic semantic IS_A hierarchy from text and corpus structure.

Two model-free signals, complementary to the within-note compound subsumption in
``subsumption.py``:

1. **Hearst lexico-syntactic patterns** (Hearst, 1992). Certain constructions
   reliably encode hyponymy: "databases *such as* Postgres", "Python *and other*
   languages", "Python *is a* language". We segment the note into sentences with
   spaCy, split each on a pattern's trigger, and anchor both sides to *known
   concepts*. Matching is done on **spaCy lemmas** — both the concept keys and
   the note tokens are lemmatised — so a singular canonical concept matches its
   plural mention with no hand-rolled inflection rule. Display surfaces are
   recovered via the lemma→surface map. High precision, low recall.

2. **Corpus term subsumption** (Sanderson & Croft, "Deriving concept hierarchies
   from text"). Across the user's notes, a concept ``x`` subsumes ``y`` when the
   notes mentioning ``y`` are a proper subset of those mentioning ``x``.

Both emit the shared ``IsAEdge`` type so the pipeline treats every hierarchy
source uniformly.
"""
from __future__ import annotations

import re
from typing import Any

from app.nlp.spacy_model import get_nlp
from app.nlp.subsumption import IsAEdge

# Trigger words whose hypernym precedes the trigger and hyponym list follows it.
_FORWARD_TRIGGERS = frozenset({"including", "especially"})


def _lemma_text(span: Any) -> str:
    """Lowercased lemma string of a spaCy token span ("networks" -> "network")."""
    return " ".join(t.lemma_.lower() for t in span)


def _match_positions(lemma: str, lemma_text: str) -> list[int]:
    """Whole-word start offsets of *lemma* within a lemmatised *lemma_text*.

    Both sides are already lemmatised, so an exact whole-word match suffices —
    no plural-tolerance regex hack needed.
    """
    return [m.start() for m in re.finditer(rf"(?<!\w){re.escape(lemma)}(?!\w)", lemma_text)]


def _present(span: Any, lemmas: list[str]) -> set[str]:
    """Subset of concept *lemmas* that appear in the token *span*."""
    lemma_text = _lemma_text(span)
    return {lem for lem in lemmas if _match_positions(lem, lemma_text)}


def _nearest_to_end(span: Any, lemmas: list[str]) -> str | None:
    """Concept lemma whose match starts latest in *span* (closest to a following trigger)."""
    lemma_text = _lemma_text(span)
    best: str | None = None
    best_pos = -1
    for lem in lemmas:
        for pos in _match_positions(lem, lemma_text):
            if pos > best_pos:
                best_pos = pos
                best = lem
    return best


def _nearest_to_start(span: Any, lemmas: list[str]) -> str | None:
    """Concept lemma whose match starts earliest in *span* (closest to a preceding trigger)."""
    lemma_text = _lemma_text(span)
    best: str | None = None
    best_pos: int | None = None
    for lem in lemmas:
        positions = _match_positions(lem, lemma_text)
        if positions and (best_pos is None or positions[0] < best_pos):
            best_pos = positions[0]
            best = lem
    return best


def _first_verb_offset(sent: Any, after: int) -> int:
    """Local index of the first VERB at/after offset *after*, else len(sent).

    Bounds a hyponym list to the noun phrases between a trigger and the clause's
    verb, so "Postgres and SQLite *store* the data" doesn't pull "data" into the
    list of database kinds.
    """
    for k in range(after, len(sent)):
        if sent[k].pos_ == "VERB":
            return k
    return len(sent)


def _emit(out: set[IsAEdge], hyper_lemma: str | None, hypo_lemmas: set[str],
          l2s: dict[str, str]) -> None:
    if hyper_lemma is None:
        return
    hyper = l2s[hyper_lemma]
    for hypo_lemma in hypo_lemmas:
        hypo = l2s[hypo_lemma]
        if hypo.lower() != hyper.lower():
            out.add(IsAEdge(child=hypo, parent=hyper))


def _such_as_and_forward(sent: Any, lemmas: list[str], l2s: dict[str, str],
                         out: set[IsAEdge]) -> None:
    """"NP_h such as NP_l ...", "NP_h including/especially NP_l ..."."""
    length = len(sent)
    for j in range(length):
        low = sent[j].lower_
        if low == "such" and j + 1 < length and sent[j + 1].lower_ == "as":
            trigger_start, after = j, j + 2
        elif low in _FORWARD_TRIGGERS:
            trigger_start, after = j, j + 1
        else:
            continue
        hyper = _nearest_to_end(sent[:trigger_start], lemmas)
        end = _first_verb_offset(sent, after)
        _emit(out, hyper, _present(sent[after:end], lemmas), l2s)


def _and_other(sent: Any, lemmas: list[str], l2s: dict[str, str], out: set[IsAEdge]) -> None:
    """"NP_l (, NP_l)* and/or other NP_h"."""
    length = len(sent)
    for j in range(1, length):
        if sent[j].lower_ == "other" and sent[j - 1].lower_ in ("and", "or"):
            hyper = _nearest_to_start(sent[j + 1:], lemmas)
            _emit(out, hyper, _present(sent[:j - 1], lemmas), l2s)


def _copular(sent: Any, lemmas: list[str], l2s: dict[str, str], out: set[IsAEdge]) -> None:
    """"NP_l is/are a/an NP_h" — class membership (article required)."""
    length = len(sent)
    for j in range(length):
        if sent[j].lower_ in ("is", "are") and j + 1 < length and sent[j + 1].lower_ in ("a", "an"):
            hyper = _nearest_to_start(sent[j + 2:], lemmas)
            hypo = _nearest_to_end(sent[:j], lemmas)
            if hyper is not None and hypo is not None and l2s[hyper].lower() != l2s[hypo].lower():
                out.add(IsAEdge(child=l2s[hypo], parent=l2s[hyper]))


def hearst_is_a(text: str, concepts: list[tuple[str, str]], *, doc: Any = None) -> list[IsAEdge]:
    """Emit IS_A edges where a Hearst pattern links two known concepts.

    ``concepts`` is a list of ``(surface, lemma)`` pairs. Matching is bounded to
    noun-phrase / clause structure via spaCy tokens and done on lemmas, keeping
    precision high. ``doc`` reuses an already-parsed spaCy ``Doc`` for *text* to
    avoid parsing the note a second time; parsed here when omitted.
    """
    if not text or not concepts:
        return []

    l2s: dict[str, str] = {}
    for surface, lemma in concepts:
        key = (lemma or surface.lower()).strip()
        if key:
            l2s.setdefault(key, surface)
    lemmas = list(l2s)

    edges: set[IsAEdge] = set()
    if doc is None:
        doc = get_nlp()(text)
    for sent in doc.sents:
        _such_as_and_forward(sent, lemmas, l2s, edges)
        _and_other(sent, lemmas, l2s, edges)
        _copular(sent, lemmas, l2s, edges)

    return sorted(edges, key=lambda e: (e.child.lower(), e.parent.lower()))


def corpus_subsumption(
    concept_note_sets: dict[str, set[str]],
    *,
    min_support: int = 2,
) -> list[IsAEdge]:
    """Derive IS_A edges via Sanderson-Croft term subsumption across notes.

    ``concept_note_sets`` maps each concept surface to the set of note ids that
    mention it. A concept ``y`` is-a ``x`` when ``notes(y)`` is a proper subset of
    ``notes(x)`` and ``y`` is mentioned in at least ``min_support`` notes. Each
    ``y`` is linked to its *nearest* parent (smallest subsuming note set).
    """
    items = [
        (concept, notes)
        for concept, notes in concept_note_sets.items()
        if len(notes) >= min_support
    ]

    edges: list[IsAEdge] = []
    for child, child_notes in items:
        nearest_parent: str | None = None
        nearest_size: int | None = None
        for parent, parent_notes in concept_note_sets.items():
            if parent == child:
                continue
            if child_notes < parent_notes:
                size = len(parent_notes)
                if nearest_size is None or size < nearest_size or (
                    size == nearest_size and parent < (nearest_parent or "")
                ):
                    nearest_parent = parent
                    nearest_size = size
        if nearest_parent is not None:
            edges.append(IsAEdge(child=child, parent=nearest_parent))

    return sorted(edges, key=lambda e: (e.child.lower(), e.parent.lower()))


__all__ = ["hearst_is_a", "corpus_subsumption"]
