def add_tag(tag: str, tags: list = None) -> list:
    if tags is None:
        tags = []
    tags.append(tag)
    return tags
