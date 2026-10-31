"""Correct implementation fixture for baseline QA testing.

Owner: Keval (W2 QA Foundation)
Reference: Docs/week2.md §5
"""

from typing import List, Union


def calculate_average(numbers: List[Union[int, float]]) -> float:
    """Calculate the arithmetic mean of a list of numbers.

    Returns 0.0 if the input list is empty.
    """
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def find_maximum(items: List[Union[int, float]]) -> Union[int, float, None]:
    """Return the largest element in the list, or None if empty."""
    if not items:
        return None
    largest = items[0]
    for val in items[1:]:
        if val > largest:
            largest = val
    return largest


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a numerical value between a lower and upper bound."""
    if min_val > max_val:
        raise ValueError(f"min_val ({min_val}) cannot exceed max_val ({max_val})")
    return max(min_val, min_val if value < min_val else min(value, max_val))
