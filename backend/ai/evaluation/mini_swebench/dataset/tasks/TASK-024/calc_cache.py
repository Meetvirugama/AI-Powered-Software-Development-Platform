import functools
@functools.lru_cache(maxsize=128)
def compute_fibonacci(n: int) -> int:
    if n <= 1:
        return max(0, n)
    return compute_fibonacci(n - 1) + compute_fibonacci(n - 2)
