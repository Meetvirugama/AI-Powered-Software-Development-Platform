def adjust_timestamp(base_ts: int, offset_seconds: int) -> int:
    result = base_ts + offset_seconds
    return max(0, result)
