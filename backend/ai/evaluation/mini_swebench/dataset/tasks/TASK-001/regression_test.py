from user_service import extract_domain
assert extract_domain({'email': 'alice@example.com'}) == 'example.com'
