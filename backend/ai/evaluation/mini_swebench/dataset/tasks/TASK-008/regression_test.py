from config import get_db_port
assert get_db_port({'database': {'port': 5433}}) == 5433
