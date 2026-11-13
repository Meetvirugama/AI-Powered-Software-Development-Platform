from router import find_item_response
res = find_item_response({'i1': {'name': 'Box'}}, 'i1')
assert res['status'] == 200
assert res['data']['name'] == 'Box'
