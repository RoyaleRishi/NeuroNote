"""Global salience rescale for graph node confidence.

The raw node-salience score is ``cosine(concept, note)`` (see
``app/nlp/salience.py``), which in practice lives in roughly ``0.1–0.6``. Exposing
that compressed band directly makes a 0–1 confidence slider feel unusable (the
useful range hides above ~0.6). We rescale it onto a friendly 0–1 scale with a
**single global constant** — identical for every user and every note — so a given
threshold means the same absolute thing everywhere (no per-note leniency).
"""
from __future__ import annotations

# Single global constant: raw cosine salience at/above this maps to 1.0. Chosen
# from the empirical salience distribution (scores cluster in ~0.1–0.6). Tune
# here, in one place, if the embedding model changes — never per note/user.
SALIENCE_RESCALE_CEILING = 0.6


def normalize_salience(raw: float) -> float:
    """Map a raw cosine salience score onto an absolute 0–1 scale.

    Linear rescale clamped to ``[0, 1]``: ``raw / SALIENCE_RESCALE_CEILING``.
    """
    if raw <= 0.0:
        return 0.0
    return min(1.0, raw / SALIENCE_RESCALE_CEILING)
