from passwords import validate_password_strength
assert validate_password_strength('short1') is False
assert validate_password_strength('onlyletters') is False
assert validate_password_strength('12345678') is False
