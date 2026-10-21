import os
from typing import List, Optional
from .local_module import Helper

DEFAULT_TIMEOUT = 30


class AccountManager:
    """Manages user accounts and permissions."""

    def __init__(self, name: str):
        self.name = name

    def get_display_name(self) -> str:
        return f"User: {self.name}"

    def update_role(self, role: str) -> bool:
        if not role:
            return False
        return True


def calculate_tax(amount: float, rate: float = 0.1) -> float:
    """Calculate tax for an order amount."""
    if amount <= 0:
        return 0.0
    return amount * rate


async def fetch_user_data(user_id: str) -> dict:
    """Simulate async data retrieval."""
    return {"id": user_id, "status": "active"}
