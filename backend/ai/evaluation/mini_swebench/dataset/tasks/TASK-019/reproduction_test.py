import pytest
from retry import execute_with_retry
calls = [0]
def fail():
    calls[0] += 1
    raise ValueError('Fail')
with pytest.raises(ValueError):
    execute_with_retry(fail, max_attempts=3)
assert calls[0] == 3
