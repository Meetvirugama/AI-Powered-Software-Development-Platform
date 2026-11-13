import datetime
from serializer import json_dump_helper
now = datetime.datetime(2026, 11, 13, 10, 0, 0)
out = json_dump_helper({'created_at': now})
assert '2026-11-13T10:00:00' in out
