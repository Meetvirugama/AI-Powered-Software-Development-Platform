from normalize import normalize_search_term, search_contains
assert normalize_search_term('  HELLO WORLD  ') == 'hello world'
assert search_contains('My Product Description', '  product  ') is True
