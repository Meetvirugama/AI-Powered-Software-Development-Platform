def sanitize_pagination_limit(limit: int, max_limit: int = 100) -> int:
    if limit <= 0:
        return 10
    return min(limit, max_limit)
