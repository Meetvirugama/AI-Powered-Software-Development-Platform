import datetime
def parse_iso_utc(date_str: str) -> datetime.datetime:
    clean = date_str.replace('Z', '+00:00')
    return datetime.datetime.fromisoformat(clean)
