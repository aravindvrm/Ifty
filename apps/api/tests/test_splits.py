from __future__ import annotations

import pytest

from app.analytics.splits import adjusted_delta, cumulative_split_factor


def test_two_for_one_split_adjustment():
    factor = cumulative_split_factor([(2, 1)])
    adjusted_previous, delta = adjusted_delta(previous_shares=100, current_shares=200, split_ratios=[(2, 1)])

    assert factor == 2.0
    assert adjusted_previous == 200.0
    assert delta == 0.0


def test_reverse_split_adjustment():
    factor = cumulative_split_factor([(1, 4)])
    adjusted_previous, delta = adjusted_delta(previous_shares=400, current_shares=100, split_ratios=[(1, 4)])

    assert factor == 0.25
    assert adjusted_previous == 100.0
    assert delta == 0.0


def test_multiple_splits_adjustment():
    factor = cumulative_split_factor([(2, 1), (3, 2)])
    adjusted_previous, delta = adjusted_delta(
        previous_shares=100,
        current_shares=300,
        split_ratios=[(2, 1), (3, 2)],
    )

    assert factor == 3.0
    assert adjusted_previous == 300.0
    assert delta == 0.0


def test_split_denominator_zero_raises():
    with pytest.raises(ValueError):
        cumulative_split_factor([(2, 0)])

