import jwt
from datetime import datetime, timedelta

def create_access_token(data: dict):
    """Generates a JWT access token for API authentication."""
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(minutes=15)})
    return jwt.encode(to_encode, "supersecretkey", algorithm="HS256")
