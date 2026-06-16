"""Unit tests for the global salience rescale (graph node confidence)."""
from __future__ import annotations

import pytest

from app.services.graph_confidence import SALIENCE_RESCALE_CEILING, normalize_salience


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.0, 0.0),
        (-0.5, 0.0),  # negatives clamp to 0
        (0.3, 0.5),   # mid-band -> 0.5 (0.3 / 0.6)
        (0.6, 1.0),   # at ceiling -> 1.0
        (0.9, 1.0),   # above ceiling clamps to 1.0
        (1.0, 1.0),
    ],
)
def test_normalize_salience_maps_to_absolute_0_1(raw: float, expected: float) -> None:
    assert normalize_salience(raw) == pytest.approx(expected)


def test_normalize_salience_is_monotonic_within_band() -> None:
    """A higher raw salience never yields a lower normalized value."""
    values = [normalize_salience(x / 100) for x in range(0, 100)]
    assert values == sorted(values)


def test_ceiling_constant_is_the_single_global_knob() -> None:
    # 0.6 is the documented global ceiling; guard against accidental drift.
    assert SALIENCE_RESCALE_CEILING == 0.6
