from __future__ import annotations

from typing import Iterable


def cumulative_split_factor(split_ratios: Iterable[tuple[float, float]]) -> float:
    factor = 1.0
    for num, den in split_ratios:
        if den == 0:
            raise ValueError("Split denominator cannot be zero.")
        factor *= float(num) / float(den)
    return factor


def adjusted_delta(
    previous_shares: float,
    current_shares: float,
    split_ratios: Iterable[tuple[float, float]],
) -> tuple[float, float]:
    factor = cumulative_split_factor(split_ratios)
    adjusted_previous = float(previous_shares) * factor
    return adjusted_previous, float(current_shares) - adjusted_previous

