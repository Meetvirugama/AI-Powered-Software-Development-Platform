def filter_records(records: list, status: str = None) -> list:
    if status is None:
        return records
    return [r for r in records if r.get('status') == status]
