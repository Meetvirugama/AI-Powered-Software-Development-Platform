from bounds import sanitize_pagination_limit
assert sanitize_pagination_limit(500, max_limit=100) == 100
assert sanitize_pagination_limit(0) == 10
assert sanitize_pagination_limit(-5) == 10
