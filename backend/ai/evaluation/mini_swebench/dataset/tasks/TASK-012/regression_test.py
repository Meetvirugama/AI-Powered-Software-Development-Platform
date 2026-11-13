from bounds import sanitize_pagination_limit
assert sanitize_pagination_limit(50) == 50
