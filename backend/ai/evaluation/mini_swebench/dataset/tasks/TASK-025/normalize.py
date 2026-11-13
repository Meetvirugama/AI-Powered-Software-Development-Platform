def normalize_search_term(term: str) -> str:
    if not term:
        return ''
    return term.strip().lower()

def search_contains(haystack: str, needle: str) -> bool:
    return normalize_search_term(needle) in normalize_search_term(haystack)
