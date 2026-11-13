from serializer import json_dump_helper
assert json_dump_helper({'key': 'value'}) == '{"key": "value"}'
