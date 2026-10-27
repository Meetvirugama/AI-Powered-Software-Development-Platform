"""Tested service fixture for QA testing.

Owner: Keval (W2 QA Foundation)
Reference: Docs/week2.md §5
Purpose: Represents an established service that already has a corresponding test suite.
"""

import re


def validate_email_address(email: str) -> bool:
    """Validate whether an email string conforms to basic RFC format."""
    if not email or not isinstance(email, str):
        return False
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email.strip()))


def format_display_name(first_name: str, last_name: str, title: str = "") -> str:
    """Format full human name with optional professional title."""
    parts = [p.strip() for p in (title, first_name, last_name) if p and p.strip()]
    return " ".join(parts)
