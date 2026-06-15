"""Unit tests for deterministic semantic hierarchy (Hearst + corpus subsumption).

Hearst tests pass concepts as ``(surface, lemma)`` pairs, mirroring what the
pipeline supplies from spaCy lemmatisation at extraction time.
"""
from __future__ import annotations

from app.nlp.hierarchy import corpus_subsumption, hearst_is_a
from app.nlp.spacy_model import get_nlp
from app.nlp.subsumption import IsAEdge


def _concepts(text: str, surfaces: list[str]) -> list[tuple[str, str]]:
    """Build (surface, lemma) pairs with lemmas taken from how each surface
    actually appears *in this text* — mirroring extraction exactly (same model,
    same in-context tokens), so the concept lemma always agrees with what
    hearst_is_a computes on the same text (even for spaCy quirks like
    'Postgres' -> 'postgre')."""
    doc = get_nlp()(text)
    lowers = [t.lower_ for t in doc]
    pairs: list[tuple[str, str]] = []
    for surf in surfaces:
        toks = surf.lower().split()
        lemma = surf.lower()
        for i in range(len(doc) - len(toks) + 1):
            if lowers[i:i + len(toks)] == toks:
                lemma = " ".join(doc[i + k].lemma_.lower() for k in range(len(toks)))
                break
        pairs.append((surf, lemma))
    return pairs


# ---- Hearst patterns ----

def test_hearst_such_as():
    text = "Relational databases such as Postgres and SQLite are widely used."
    edges = set(hearst_is_a(text, _concepts(text, ["databases", "Postgres", "SQLite"])))
    assert IsAEdge(child="Postgres", parent="databases") in edges
    assert IsAEdge(child="SQLite", parent="databases") in edges


def test_hearst_and_other():
    text = "Postgres and other databases support transactions."
    edges = set(hearst_is_a(text, _concepts(text, ["Postgres", "databases"])))
    assert IsAEdge(child="Postgres", parent="databases") in edges


def test_hearst_copular_is_a():
    text = "Python is a programming language."
    edges = set(hearst_is_a(text, _concepts(text, ["Python", "programming language"])))
    assert IsAEdge(child="Python", parent="programming language") in edges


def test_hearst_including():
    text = "Several languages including Python and Rust are popular."
    edges = set(hearst_is_a(text, _concepts(text, ["languages", "Python", "Rust"])))
    assert IsAEdge(child="Python", parent="languages") in edges
    assert IsAEdge(child="Rust", parent="languages") in edges


def test_hearst_plural_concept_matches_via_lemma():
    """A singular canonical concept matches its plural mention through lemmas."""
    text = "Transformers are a neural network used widely."
    # "Transformers" in-text lemmatises to "transformer" — same key the concept carries.
    edges = set(hearst_is_a(text, _concepts(text, ["Transformers", "neural network"])))
    assert any(e.parent == "neural network" for e in edges)


def test_hearst_hyponym_list_bounded_by_verb():
    text = "Databases such as Postgres and SQLite store the training data."
    edges = set(hearst_is_a(
        text, _concepts(text, ["databases", "Postgres", "SQLite", "training data"])))
    assert IsAEdge(child="Postgres", parent="databases") in edges
    # "training data" is past the verb "store" -> not a kind of database.
    assert IsAEdge(child="training data", parent="databases") not in edges


def test_hearst_requires_known_concepts():
    text = "Databases such as Postgres are common."
    edges = hearst_is_a(text, _concepts(text, ["databases"]))
    assert edges == []


# ---- Corpus subsumption ----

def test_corpus_subsumption_proper_subset():
    note_sets = {"network": {"n1", "n2", "n3"}, "neural network": {"n1", "n2"}}
    edges = corpus_subsumption(note_sets, min_support=2)
    assert IsAEdge(child="neural network", parent="network") in edges


def test_corpus_subsumption_nearest_parent():
    note_sets = {
        "thing": {"n1", "n2", "n3", "n4"},
        "network": {"n1", "n2", "n3"},
        "neural network": {"n1", "n2"},
    }
    edges = corpus_subsumption(note_sets, min_support=2)
    parents = {e.parent for e in edges if e.child == "neural network"}
    assert parents == {"network"}


def test_corpus_subsumption_min_support_filters_singletons():
    note_sets = {"network": {"n1", "n2"}, "transformer": {"n1"}}
    edges = corpus_subsumption(note_sets, min_support=2)
    assert all(e.child != "transformer" for e in edges)


def test_corpus_subsumption_no_edge_for_disjoint_sets():
    note_sets = {"alpha": {"n1", "n2"}, "beta": {"n3", "n4"}}
    assert corpus_subsumption(note_sets, min_support=2) == []
