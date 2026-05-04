from __future__ import annotations

import re

from app.nlp.spotting import extract_entities_with_mentions
from app.nlp.spotting import extract_entities_with_mentions_and_metrics
from app.nlp.types import BlockTextInput


def test_spotter_uses_dictionary_terms_with_block_offsets() -> None:
    entities, mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(
                block_index=0,
                content_text="Machine Learning improves graph reasoning.",
            )
        ],
        dictionary_terms=["machine learning", "graph reasoning"],
    )

    assert [entity.text for entity in entities] == ["graph reasoning", "Machine Learning"]
    assert len(mentions) == 2
    assert mentions[0].block_index == 0
    assert mentions[0].mention_text == "Machine Learning"
    assert mentions[0].start_offset == 0
    assert mentions[0].end_offset == 16
    assert mentions[1].mention_text == "graph reasoning"


def test_spotter_falls_back_to_title_case_and_acronyms() -> None:
    entities, mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(
                block_index=1,
                content_text="Entity Resolution supports ML systems.",
            )
        ],
    )

    assert {entity.text for entity in entities} == {"Entity Resolution", "ML"}
    assert all(mention.block_index == 1 for mention in mentions)


def test_spotter_dedupes_and_sorts_mentions_deterministically() -> None:
    entities, mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(block_index=0, content_text="ML supports ML workflows."),
            BlockTextInput(block_index=1, content_text="Machine Learning supports ML."),
        ],
        dictionary_terms=["machine learning", "ml"],
    )

    assert any(entity.text == "ML" for entity in entities)
    assert len(mentions) == 4
    assert [(item.block_index, item.start_offset) for item in mentions] == [
        (0, 0),
        (0, 12),
        (1, 0),
        (1, 26),
    ]


def test_spotter_captures_generic_lowercase_multiword_phrases() -> None:
    entities, mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(
                block_index=0,
                content_text="bayesian inference improves variational methods for optimization",
            )
        ],
        dictionary_terms=[],
    )

    entity_texts = {entity.text.lower() for entity in entities}
    assert "bayesian inference" in entity_texts
    assert "variational methods" in entity_texts
    assert len(mentions) >= 2


def test_spotter_avoids_clubbed_lowercase_connector_phrases() -> None:
    entities, _mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(
                block_index=0,
                content_text="machine learning improves graph reasoning across notes",
            )
        ],
        dictionary_terms=[],
    )

    entity_texts = {entity.text.lower() for entity in entities}
    assert "machine learning" in entity_texts
    assert "graph reasoning" in entity_texts
    assert "graph reasoning across" not in entity_texts
    assert "reasoning across notes" not in entity_texts
    assert "across notes" not in entity_texts


def test_spotter_captures_repeated_lowercase_single_token_across_blocks() -> None:
    entities, mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(block_index=0, content_text="eren explores titan forms"),
            BlockTextInput(block_index=1, content_text="mikasa supports eren in battle"),
        ],
        dictionary_terms=[],
    )

    entity_texts = {entity.text.lower() for entity in entities}
    assert "eren" in entity_texts
    eren_mentions = [item for item in mentions if item.mention_text.lower() == "eren"]
    assert len(eren_mentions) == 2
    assert {(item.block_index, item.start_offset) for item in eren_mentions} == {(0, 0), (1, 16)}


def test_fallback_does_not_extract_sentence_starting_stopwords() -> None:
    # Sentence-starting stopwords like "For", "The", "In" match _TITLE_CASE_PATTERN
    # because they are capitalized. They must be rejected.
    entities, _mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(
                block_index=0,
                content_text="For the purpose of learning. The model trains on data. In this case the system works.",
            )
        ],
        dictionary_terms=[],
        enable_regex_fallback=True,
    )
    entity_keys = {entity.text.lower() for entity in entities}
    assert "for" not in entity_keys
    assert "the" not in entity_keys
    assert "in" not in entity_keys


def test_fallback_preserves_real_title_case_entities() -> None:
    # Non-stopword title-case names should still be extracted.
    entities, _mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(
                block_index=0,
                content_text="For the purpose of understanding Neural Networks, the Transformer Architecture is key.",
            )
        ],
        dictionary_terms=[],
        enable_regex_fallback=True,
    )
    entity_keys = {entity.text.lower() for entity in entities}
    assert "neural networks" in entity_keys
    assert "transformer architecture" in entity_keys
    assert "for" not in entity_keys
    assert "the" not in entity_keys


def test_spotter_ignores_repeated_noise_tokens() -> None:
    entities, _mentions = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(block_index=0, content_text="hello graph hello world"),
            BlockTextInput(block_index=1, content_text="hello from the graph"),
        ],
        dictionary_terms=[],
    )

    entity_texts = {entity.text.lower() for entity in entities}
    assert "hello" not in entity_texts


class _FakeEnt:
    def __init__(self, *, text: str, start_char: int, end_char: int, label_: str = "ORG") -> None:
        self.text = text
        self.start_char = start_char
        self.end_char = end_char
        self.label_ = label_


class _FakeDoc:
    def __init__(self, ents: list[_FakeEnt]) -> None:
        self.ents = ents


class _FakeRuler:
    def __init__(self) -> None:
        self.patterns: list[dict[str, object]] = []

    def add_patterns(self, patterns: list[dict[str, object]]) -> None:
        self.patterns.extend(patterns)


class _FakeNlp:
    def __init__(self) -> None:
        self.pipe_names = ["ner"]
        self._ruler = _FakeRuler()

    def add_pipe(self, name: str, before: str | None = None) -> _FakeRuler:
        if name == "entity_ruler" and name not in self.pipe_names:
            self.pipe_names.insert(0, name if before == "ner" else name)
        return self._ruler

    def get_pipe(self, name: str) -> _FakeRuler:
        if name != "entity_ruler":
            raise KeyError(name)
        return self._ruler

    def __call__(self, text: str) -> _FakeDoc:
        lowered = text.lower()
        ents: list[_FakeEnt] = []
        target = "graph reasoning"
        start = lowered.find(target)
        if start >= 0:
            ents.append(_FakeEnt(text=text[start : start + len(target)], start_char=start, end_char=start + len(target)))
        return _FakeDoc(ents)


def test_spotter_hybrid_mode_extracts_lowercase_entities_and_dedupes_overlap() -> None:
    fake_nlp = _FakeNlp()
    entities, mentions, metrics = extract_entities_with_mentions_and_metrics(
        blocks=[
            BlockTextInput(block_index=0, content_text="graph reasoning improves retrieval"),
            BlockTextInput(block_index=1, content_text="graph reasoning improves notes"),
        ],
        dictionary_terms=["graph reasoning"],
        seed_terms=["entity resolution"],
        extraction_profile="hybrid-spacy",
        model_handle=fake_nlp,
        enable_regex_fallback=True,
    )

    assert any(entity.text.lower() == "graph reasoning" for entity in entities)
    assert [(mention.block_index, mention.start_offset, mention.end_offset) for mention in mentions] == [
        (0, 0, 15),
        (1, 0, 15),
    ]
    assert metrics.dictionary_hits == 2
    assert metrics.spacy_hits == 2
    assert metrics.merged_mentions == 2


# ── Quality gate tests ────────────────────────────────────────────────────────

from app.nlp.spotting import _passes_quality_gate
import re as _re


def test_quality_gate_rejects_single_char() -> None:
    assert _passes_quality_gate("a") is False


def test_quality_gate_rejects_two_char_lowercase() -> None:
    assert _passes_quality_gate("is") is False
    assert _passes_quality_gate("in") is False
    assert _passes_quality_gate("to") is False


def test_quality_gate_keeps_two_char_acronym() -> None:
    assert _passes_quality_gate("ML") is True
    assert _passes_quality_gate("AI") is True


def test_quality_gate_rejects_pure_digits() -> None:
    assert _passes_quality_gate("123") is False
    assert _passes_quality_gate("42") is False


def test_quality_gate_rejects_camel_case() -> None:
    assert _passes_quality_gate("myVar") is False
    assert _passes_quality_gate("setState") is False
    assert _passes_quality_gate("useEffect") is False


def test_quality_gate_rejects_snake_case() -> None:
    assert _passes_quality_gate("my_var") is False
    assert _passes_quality_gate("_private") is False


def test_quality_gate_rejects_dollar_sign() -> None:
    assert _passes_quality_gate("$event") is False


def test_quality_gate_rejects_code_keywords() -> None:
    assert _passes_quality_gate("const") is False
    assert _passes_quality_gate("async") is False
    assert _passes_quality_gate("null") is False
    assert _passes_quality_gate("undefined") is False


def test_quality_gate_keeps_valid_concepts() -> None:
    assert _passes_quality_gate("machine learning") is True
    assert _passes_quality_gate("gradient descent") is True
    assert _passes_quality_gate("neural network") is True
    assert _passes_quality_gate("SQL") is True


def test_spotter_quality_gate_filters_code_variable_from_block() -> None:
    # Feed text containing camelCase code variable names through the full
    # extraction pipeline and assert they are filtered out by the quality gate.
    entities, _ = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(
                block_index=0,
                content_text="The useEffect and useState hooks trigger setState on render in React components.",
            )
        ],
    )
    texts = {e.text for e in entities}
    assert "useEffect" not in texts
    assert "useState" not in texts
    assert "setState" not in texts
    # Verify no camelCase slipped through at all
    for text in texts:
        assert not re.match(r"^[a-z]+[A-Z]", text), f"camelCase leaked: {text}"


def test_quality_gate_keeps_english_noun_class_and_type() -> None:
    # "class" and "type" are legitimate English nouns in multi-word phrases.
    assert _passes_quality_gate("class diagram") is True
    assert _passes_quality_gate("type theory") is True
    assert _passes_quality_gate("interface design") is True
