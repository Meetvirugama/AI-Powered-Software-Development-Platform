def get_page_items(items: list, page: int, limit: int) -> list:
    offset = (page - 1) * limit
    return items[offset : offset + limit]
