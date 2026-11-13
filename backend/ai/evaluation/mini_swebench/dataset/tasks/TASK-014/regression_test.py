from orders import validate_order_quantity
assert validate_order_quantity(1) == 1
assert validate_order_quantity(10) == 10
