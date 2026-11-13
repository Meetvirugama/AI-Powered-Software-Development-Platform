from user_service import extract_domain
assert extract_domain({'email': None}) == 'unknown'
assert extract_domain({}) == 'unknown'
