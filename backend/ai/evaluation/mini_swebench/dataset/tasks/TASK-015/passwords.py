def validate_password_strength(password: str) -> bool:
    if not password or len(password) < 8:
        return False
    has_digit = any(c.isdigit() for c in password)
    has_alpha = any(c.isalpha() for c in password)
    return has_digit and has_alpha
