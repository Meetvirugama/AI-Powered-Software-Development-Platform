def find_common_tags(tags1: list[str], tags2: list[str]) -> list[str]:
    s2 = set(tags2)
    return [t for t in tags1 if t in s2]
