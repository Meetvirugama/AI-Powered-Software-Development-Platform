import redis

# Redis caching layer implementation
redis_client = redis.Redis(host='localhost', port=6379, db=0)

def get_cached_user(user_id: int):
    return redis_client.get(f"user:{user_id}")
