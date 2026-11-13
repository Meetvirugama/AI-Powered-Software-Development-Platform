from filter import filter_records
recs = [{'id': 1, 'status': 'active'}, {'id': 2, 'status': 'closed'}]
assert len(filter_records(recs)) == 2
