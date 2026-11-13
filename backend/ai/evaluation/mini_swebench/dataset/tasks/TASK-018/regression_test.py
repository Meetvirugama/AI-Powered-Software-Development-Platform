from db_pool import run_query_with_cleanup
class MockConn:
    def __init__(self):
        self.closed = False
    def execute(self, q):
        return 'ok'
    def close(self):
        self.closed = True
m = MockConn()
assert run_query_with_cleanup(m, 'SELECT 1') == 'ok'
assert m.closed is True
