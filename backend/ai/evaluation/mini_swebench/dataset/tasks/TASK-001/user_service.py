def extract_domain(user: dict) -> str:
    email = user.get('email')
    if not email:
        return 'unknown'
    return email.split('@')[1]
