import pytest
from orders import validate_order_quantity
with pytest.raises(ValueError):
    validate_order_quantity(0)
with pytest.raises(ValueError):
    validate_order_quantity(-5)
