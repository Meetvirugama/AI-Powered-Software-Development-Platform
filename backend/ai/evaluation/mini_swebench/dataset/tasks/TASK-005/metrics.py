def compute_percentage(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100.0, 2)
