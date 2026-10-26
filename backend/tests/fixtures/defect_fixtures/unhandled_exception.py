"""Unhandled exception fixture for QA testing.

Owner: Keval (W2 QA Foundation)
Reference: Docs/week2.md §5
Defect: Performs I/O, parsing, or division without catching expected runtime exceptions.
"""

import json
from typing import Any, Dict


def parse_user_config(raw_payload: str) -> Dict[str, Any]:
    """Parse JSON configuration string.

    DEFECT: Raises unhandled json.JSONDecodeError if payload is malformed.
    """
    return json.loads(raw_payload)


def calculate_ratio(dividend: float, divisor: float) -> float:
    """Calculate ratio between two numbers.

    DEFECT: Raises ZeroDivisionError without checking or handling divisor == 0.
    """
    return dividend / divisor


def read_system_metric(file_path: str) -> str:
    """Read a local metric file.

    DEFECT: Raises FileNotFoundError / PermissionError without exception handling.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()
