from config import get_db_port
assert get_db_port({}) == 5432
assert get_db_port({'database': None}) == 5432
