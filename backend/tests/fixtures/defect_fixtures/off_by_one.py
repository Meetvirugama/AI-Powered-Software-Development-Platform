"""Known off-by-one defect fixture for QA testing.

Owner: Keval (W2 QA Foundation)
Reference: Docs/week2.md §5
Defect: Line 18 accesses `items[i]` with `i` ranging up to `len(items)`, causing an IndexError.
"""

from typing import Any, List


def get_first_n_items(items: List[Any], n: int) -> List[Any]:
    """Return the first n elements from a list.

    Contains a known boundary error where the range includes the upper bound inappropriately.
    """
    result = []
    # DEFECT: off-by-one in loop upper bound causes IndexError when n >= len(items)
    for i in range(0, min(n + 1, len(items) + 1)):
        result.append(items[i])
    return result


def find_index_of_item(items: List[Any], target: Any) -> int:
    """Find the index of target in items.

    DEFECT: Range reaches len(items) + 1.
    """
    for idx in range(0, len(items) + 1):  # DEFECT: off-by-one
        if items[idx] == target:
            return idx
    return -1


def get_last_element_bad(items: List[Any]) -> Any:
    """DEFECT: Indexing sequence with its exact length triggers IndexError."""
    return items[len(items)]

