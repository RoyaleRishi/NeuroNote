"""Thread-safety tests for the NLP pipeline extraction cache.

Spins many threads concurrently calling _cache_put / _cache_get /
clear_extraction_cache and asserts no exception is raised and the cache
never exceeds _EXTRACTION_CACHE_MAX.
"""
from __future__ import annotations

import threading


from app.nlp.pipeline import (
    _EXTRACTION_CACHE,
    _EXTRACTION_CACHE_MAX,
    _cache_get,
    _cache_put,
    clear_extraction_cache,
)
from app.nlp.types import NoteExtractionResult


def _stub_result(content_hash: str) -> NoteExtractionResult:
    """Minimal NoteExtractionResult for cache testing."""
    return NoteExtractionResult(
        note_id="note-stub",
        content_hash=content_hash,
        entities=[],
        relations=[],
        embedding=None,
        distinct_blocks_with_concepts=0,
    )


def test_concurrent_cache_put_get_no_exception() -> None:
    """20 threads doing put/get/clear concurrently must not raise."""
    clear_extraction_cache()
    errors: list[Exception] = []

    def worker(thread_idx: int) -> None:
        try:
            for i in range(50):
                key = f"hash-t{thread_idx}-{i}"
                _cache_put(key, _stub_result(key))
                result = _cache_get(key)
                # result may be None if evicted or cleared by another thread — that's fine
                _ = result
            if thread_idx % 5 == 0:
                clear_extraction_cache()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Exceptions in cache threads: {errors}"


def test_cache_size_never_exceeds_max() -> None:
    """After concurrent inserts the cache must not exceed _EXTRACTION_CACHE_MAX."""
    clear_extraction_cache()
    errors: list[Exception] = []

    def filler(thread_idx: int) -> None:
        try:
            for i in range(_EXTRACTION_CACHE_MAX // 4):
                key = f"fill-t{thread_idx}-{i}"
                _cache_put(key, _stub_result(key))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=filler, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Exceptions in filler threads: {errors}"
    assert len(_EXTRACTION_CACHE) <= _EXTRACTION_CACHE_MAX, (
        f"Cache size {len(_EXTRACTION_CACHE)} exceeds max {_EXTRACTION_CACHE_MAX}"
    )


def test_cache_clear_is_thread_safe() -> None:
    """clear_extraction_cache called from multiple threads must not raise."""
    errors: list[Exception] = []

    def clearer() -> None:
        try:
            for _ in range(20):
                clear_extraction_cache()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=clearer) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
