def validate_order_quantity(qty: int) -> int:
    if not isinstance(qty, int) or qty <= 0:
        raise ValueError('Quantity must be a positive integer')
    return qty
