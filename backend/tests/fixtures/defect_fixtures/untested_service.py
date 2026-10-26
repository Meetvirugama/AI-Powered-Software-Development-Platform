"""Untested service fixture for QA testing.

Owner: Keval (W2 QA Foundation)
Reference: Docs/week2.md §5
Purpose: Represents a candidate function or module that lacks unit tests.
"""

from typing import Dict, List


class PricingService:
    """Calculates discounted line items and cart totals."""

    TAX_RATE = 0.0825

    def compute_cart_total(self, items: List[Dict[str, float]], coupon_discount: float = 0.0) -> float:
        """Compute the final cost of a cart including discount and tax."""
        subtotal = sum(item.get("price", 0.0) * item.get("quantity", 1.0) for item in items)
        discounted = max(0.0, subtotal - coupon_discount)
        total_tax = discounted * self.TAX_RATE
        return round(discounted + total_tax, 2)
