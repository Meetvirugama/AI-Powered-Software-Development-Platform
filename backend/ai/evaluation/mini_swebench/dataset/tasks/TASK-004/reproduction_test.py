from auth import check_admin_access
assert check_admin_access({'is_admin': False}) is False
assert check_admin_access({}) is False
