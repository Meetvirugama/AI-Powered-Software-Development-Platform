def deduplicate_preserve_order(items: list) -> list:
    return list(dict.fromkeys(items))
