def get_db_port(config: dict, default: int = 5432) -> int:
    db = config.get('database') or {}
    return db.get('port', default)
