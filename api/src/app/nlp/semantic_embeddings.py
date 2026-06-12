"""Real semantic embeddings via sentence-transformers.

Uses all-MiniLM-L6-v2 (22 MB, 384 dimensions) which produces genuine semantic
vectors — cosine similarity reflects actual meaning similarity.

Produces the same 384-dimension output as the hash-based embedder so no DB
schema migration is needed.

Falls back gracefully if sentence-transformers is not installed.
"""
from __future__ import annotations

import logging
import threading

_LOGGER = logging.getLogger(__name__)
_MODEL_NAME = "all-MiniLM-L6-v2"

# Guards lazy model initialisation against concurrent loaders. Without this,
# parallel backfill workers can each trigger SentenceTransformer construction
# (which downloads weights and allocates GPU/CPU buffers) at the same time.
_INIT_LOCK = threading.Lock()


class SemanticEmbedder:
    """Lazy singleton wrapper around the sentence-transformers model."""

    _instance: object | None = None

    @classmethod
    def get(cls) -> object | None:
        # Double-checked locking: fast path avoids lock acquisition once the
        # model is loaded. Slow path serialises the first-time load across
        # threads so only one SentenceTransformer instance ever exists.
        if cls._instance is not None:
            return cls._instance

        with _INIT_LOCK:
            if cls._instance is not None:
                return cls._instance

            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

                cls._instance = SentenceTransformer(_MODEL_NAME)
                _LOGGER.info("Loaded semantic embedding model: %s", _MODEL_NAME)
            except ImportError:
                _LOGGER.debug("sentence-transformers not installed; semantic embeddings unavailable")
            except Exception as exc:
                _LOGGER.warning("Failed to load embedding model %s: %s", _MODEL_NAME, exc)

            return cls._instance


def build_semantic_embedding(text: str) -> list[float] | None:
    """Encode *text* using the sentence-transformer model.

    Returns a normalised 384-dimensional float list, or None if the model
    could not be loaded so the pipeline can fall back to the hash embedder.
    """
    model = SemanticEmbedder.get()
    if model is None:
        return None

    try:
        vector = model.encode(text, normalize_embeddings=True)  # type: ignore[attr-defined]
        return vector.tolist()
    except Exception as exc:
        _LOGGER.warning("Semantic embedding failed: %s", exc)
        return None


def build_semantic_embeddings(texts: list[str]) -> list[list[float]] | None:
    """Encode a batch of texts in a single sentence-transformers call.

    Uses ``model.encode(list, normalize_embeddings=True)`` which is dramatically
    faster than N single calls (one transformer forward pass per batch).
    Returns a list of 384-dimensional float lists, or ``None`` if the model
    could not be loaded — callers should then fall back to per-text encoding
    (which may itself fall back to the deterministic hash embedder).
    """
    if not texts:
        return []

    model = SemanticEmbedder.get()
    if model is None:
        return None

    try:
        vectors = model.encode(texts, normalize_embeddings=True)  # type: ignore[attr-defined]
        return [v.tolist() for v in vectors]
    except Exception as exc:
        _LOGGER.warning("Semantic batch embedding failed: %s", exc)
        return None


__all__ = [
    "SemanticEmbedder",
    "build_semantic_embedding",
    "build_semantic_embeddings",
]
