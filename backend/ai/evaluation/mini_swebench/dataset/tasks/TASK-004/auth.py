def check_admin_access(user: dict) -> bool:
    return bool(user and user.get('is_admin') is True)
