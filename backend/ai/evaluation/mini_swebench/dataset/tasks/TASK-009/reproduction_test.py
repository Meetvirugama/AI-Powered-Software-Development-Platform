from router import find_item_response
res = find_item_response({}, 'unknown')
assert res['status'] == 404
assert 'not found' in res['error'].lower()
