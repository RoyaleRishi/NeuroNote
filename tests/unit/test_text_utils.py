"""Tests for shared text utility functions."""
from __future__ import annotations

from app.utils.text import (
    collapse_whitespace,
    normalize_title,
    normalize_title_key,
    extract_wiki_link_titles,
    normalize_entity_key,
    normalize_include_types,
)


# ── collapse_whitespace ─────────────────────────────────────────────────────


class TestCollapseWhitespace:
    def test_empty_string(self) -> None:
        assert collapse_whitespace("") == ""

    def test_single_word(self) -> None:
        assert collapse_whitespace("hello") == "hello"

    def test_multiple_internal_spaces(self) -> None:
        assert collapse_whitespace("foo    bar     baz") == "foo bar baz"

    def test_leading_and_trailing_whitespace(self) -> None:
        assert collapse_whitespace("   hello world   ") == "hello world"

    def test_mixed_tabs_spaces_newlines(self) -> None:
        assert collapse_whitespace("a\t b\n\nc \td") == "a b c d"


# ── normalize_title ──────────────────────────────────────────────────────────


class TestNormalizeTitle:
    def test_collapses_whitespace(self) -> None:
        assert normalize_title("  hello   world  ") == "hello world"

    def test_strips_leading_trailing(self) -> None:
        assert normalize_title("  foo  ") == "foo"

    def test_empty_string(self) -> None:
        assert normalize_title("") == ""

    def test_tabs_and_newlines(self) -> None:
        assert normalize_title("a\t\nb") == "a b"

    def test_unicode_preserved(self) -> None:
        assert normalize_title("  café  résumé  ") == "café résumé"

    def test_single_word(self) -> None:
        assert normalize_title("hello") == "hello"


# ── normalize_title_key ─────────────────────────────────────────────────────


class TestNormalizeTitleKey:
    def test_lowercases(self) -> None:
        assert normalize_title_key("Hello World") == "hello world"

    def test_collapses_and_lowers(self) -> None:
        assert normalize_title_key("  FOO   BAR  ") == "foo bar"


# ── extract_wiki_link_titles ────────────────────────────────────────────────


class TestExtractWikiLinkTitles:
    def test_single_link(self) -> None:
        assert extract_wiki_link_titles("see [[My Note]]") == ["my note"]

    def test_multiple_links(self) -> None:
        result = extract_wiki_link_titles("[[A]] and [[B]]")
        assert result == ["a", "b"]

    def test_deduplicates(self) -> None:
        result = extract_wiki_link_titles("[[Foo]] then [[foo]]")
        assert result == ["foo"]

    def test_empty_brackets_ignored(self) -> None:
        assert extract_wiki_link_titles("[[]]") == []

    def test_nested_brackets_ignored(self) -> None:
        # Pattern excludes brackets inside — no match for nested [[a[b]c]]
        assert extract_wiki_link_titles("[[a[b]c]]") == []

    def test_no_links(self) -> None:
        assert extract_wiki_link_titles("plain text") == []

    def test_whitespace_normalized_in_title(self) -> None:
        assert extract_wiki_link_titles("[[  hello   world  ]]") == ["hello world"]

    def test_empty_after_normalization(self) -> None:
        assert extract_wiki_link_titles("[[   ]]") == []


# ── normalize_entity_key ────────────────────────────────────────────────────


class TestNormalizeEntityKey:
    def test_basic(self) -> None:
        assert normalize_entity_key("Machine Learning") == "machine-learning"

    def test_special_chars(self) -> None:
        assert normalize_entity_key("C++ Programming!") == "c-programming"

    def test_empty_fallback(self) -> None:
        assert normalize_entity_key("!!!") == "unknown"

    def test_strips_leading_trailing_dashes(self) -> None:
        assert normalize_entity_key("-foo-") == "foo"


# ── normalize_include_types ─────────────────────────────────────────────────


class TestNormalizeIncludeTypes:
    def test_valid_types(self) -> None:
        assert normalize_include_types(["note", "entity"]) == ["note", "entity"]

    def test_invalid_filtered(self) -> None:
        assert normalize_include_types(["note", "bogus"]) == ["note"]

    def test_deduplicates(self) -> None:
        assert normalize_include_types(["note", "note", "entity"]) == ["note", "entity"]

    def test_empty_returns_defaults(self) -> None:
        assert normalize_include_types([]) == ["note", "entity", "relation"]

    def test_all_invalid_returns_defaults(self) -> None:
        assert normalize_include_types(["bogus"]) == ["note", "entity", "relation"]

    def test_strips_whitespace(self) -> None:
        assert normalize_include_types(["  note  ", " entity"]) == ["note", "entity"]
