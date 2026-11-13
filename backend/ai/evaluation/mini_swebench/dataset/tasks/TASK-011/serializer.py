import datetime, json
def json_dump_helper(data: dict) -> str:
    def _default(obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        raise TypeError(f'Type {type(obj)} not serializable')
    return json.dumps(data, default=_default)
