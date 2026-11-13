from retry import execute_with_retry
assert execute_with_retry(lambda: 42) == 42
