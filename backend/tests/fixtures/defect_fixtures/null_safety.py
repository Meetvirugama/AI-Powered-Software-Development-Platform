"""Null/None safety defect fixture for QA testing.

Owner: Keval (W2 QA Foundation)
Reference: Docs/week2.md §5
Defect: Accesses attributes or dictionary keys on None without null safety guards.
"""

from typing import Any, Dict, Optional


class UserProfile:
    def __init__(self, username: str, email: Optional[str] = None) -> None:
        self.username = username
        self.email = email


def get_user_domain(user: Optional[UserProfile]) -> str:
    """Extract email domain from user profile.

    DEFECT: Does not check if `user` is None, or if `user.email` is None before splitting.
    """
    return user.email.split("@")[1]  # DEFECT: AttributeError when user or email is None


def format_header_token(headers: Dict[str, Any]) -> str:
    """Format the Bearer authorization token.

    DEFECT: Direct dictionary access without checking existence or None value.
    """
    token_str: Optional[str] = headers.get("Authorization")
    return token_str.strip().replace("Bearer ", "")  # DEFECT: AttributeError if token_str is None
