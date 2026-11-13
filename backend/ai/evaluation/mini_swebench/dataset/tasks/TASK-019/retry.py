def execute_with_retry(func, max_attempts: int = 3):
    attempts = 0
    last_error = None
    while attempts < max_attempts:
        try:
            return func()
        except Exception as exc:
            last_error = exc
            attempts += 1
    raise last_error
