# Fix NoneType error in email domain parser

Calling extract_domain(user) crashes with AttributeError when user['email'] is None or missing.
