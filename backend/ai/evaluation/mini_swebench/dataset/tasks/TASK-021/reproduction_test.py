from flattener import flatten_dict
inp = {'app': {'server': {'port': 8080}}}
assert flatten_dict(inp) == {'app.server.port': 8080}
