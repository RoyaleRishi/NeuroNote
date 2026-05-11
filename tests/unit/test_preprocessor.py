# tests/unit/test_preprocessor.py
from __future__ import annotations

from app.nlp.preprocessor import preprocess_content


def test_strips_inline_code() -> None:
    raw = "Use `setState` to update `myVar` in React."
    result = preprocess_content(raw)
    assert "setState" not in result
    assert "myVar" not in result
    assert "React" in result


def test_strips_fenced_code_block() -> None:
    raw = "Here is code:\n```python\nfor x in range(10):\n    print(x)\n```\nEnd."
    result = preprocess_content(raw)
    assert "for x" not in result
    assert "print" not in result
    assert "Here is code" in result
    assert "End" in result


def test_strips_markdown_link_keeps_display_text() -> None:
    raw = "Read [gradient descent](https://example.com/gd) for details."
    result = preprocess_content(raw)
    assert "https://example.com" not in result
    assert "gradient descent" in result


def test_strips_image_keeps_alt_text() -> None:
    raw = "See ![neural network diagram](https://example.com/nn.png) above."
    result = preprocess_content(raw)
    assert "https://example.com" not in result
    assert "neural network diagram" in result


def test_collapses_whitespace() -> None:
    raw = "  multiple   spaces\t\there  "
    result = preprocess_content(raw)
    assert "  " not in result
    assert result == "multiple spaces here"


def test_empty_string_returns_empty() -> None:
    assert preprocess_content("") == ""


def test_no_markup_unchanged() -> None:
    raw = "Machine Learning uses gradient descent."
    result = preprocess_content(raw)
    assert result == raw
