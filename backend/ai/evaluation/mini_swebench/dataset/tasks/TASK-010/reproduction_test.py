from filter import filter_records
recs = [{'id': 1, 'status': 'active'}, {'id': 2, 'status': 'closed'}]
filtered = filter_records(recs, status='active')
assert len(filtered) == 1
assert filtered[0]['id'] == 1
