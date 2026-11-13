from validator import is_valid_email
assert is_valid_email('user@localhost') is False
assert is_valid_email('plainaddress') is False
assert is_valid_email('') is False
