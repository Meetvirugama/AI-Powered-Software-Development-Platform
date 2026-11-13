from db_pool import run_query_with_cleanup
class MockConn:
    def __init__(self):
        self.closed = False
    def execute(self, q):
        raise RuntimeError('DB failed')
    def close(self):
        self.closed = True
m = MockConn()
try:
    run_query_with_cleanup(m, 'SELECT 1')
except RuntimeError:
    pass
assert m.closed is True
