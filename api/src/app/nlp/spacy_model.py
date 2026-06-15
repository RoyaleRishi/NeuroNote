"""Shared spaCy model singleton.

The deterministic concept pipeline uses spaCy for two things: noun-chunk
candidate generation (``extraction.py``) and Hearst lexico-syntactic pattern
matching (``hierarchy.py``). Both share a single ``en_core_web_sm`` instance so
the model is loaded — and its weights resident — exactly once per process.

Mirrors the lazy double-checked-locking pattern used by
``semantic_embeddings.SemanticEmbedder`` so concurrent backfill workers can't
each trigger a separate model load.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

_LOGGER = logging.getLogger(__name__)
_MODEL_NAME = "en_core_web_sm"

_INIT_LOCK = threading.Lock()
_INSTANCE: Any = None


def get_nlp() -> Any:
    """Return the shared spaCy ``Language`` pipeline, loading it on first call.

    Raises ``OSError`` if the model is not installed — the deterministic
    pipeline cannot run without it, so failing loudly is correct.
    """
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE

    with _INIT_LOCK:
        if _INSTANCE is None:
            import spacy  # imported lazily so non-NLP code paths don't pay for it

            _INSTANCE = spacy.load(_MODEL_NAME)
            _LOGGER.info("Loaded spaCy model: %s", _MODEL_NAME)
    return _INSTANCE


def prewarm_spacy() -> None:
    """Eagerly load the spaCy model (call at app startup to avoid first-note lag)."""
    get_nlp()


__all__ = ["get_nlp", "prewarm_spacy"]
