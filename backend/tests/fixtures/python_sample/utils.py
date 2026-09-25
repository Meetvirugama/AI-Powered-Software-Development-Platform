import hashlib

def hash_password(password: str) -> str:
    """Hashes a user password for secure storage."""
    return hashlib.sha256(password.encode()).hexdigest()
