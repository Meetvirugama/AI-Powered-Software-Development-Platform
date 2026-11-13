def run_query_with_cleanup(conn, query: str):
    try:
        return conn.execute(query)
    finally:
        conn.close()
