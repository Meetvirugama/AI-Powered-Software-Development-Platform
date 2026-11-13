from validator import is_valid_email
assert is_valid_email('alice@example.com') is True
assert is_valid_email('bob.smith+tag@sub.domain.co.uk') is True
