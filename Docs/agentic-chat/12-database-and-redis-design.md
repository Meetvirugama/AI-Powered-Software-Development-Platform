# 12 — Database and Redis Design

## 1. Relational & Vector Storage (PostgreSQL + pgvector)

Bounded Agentic Repository Chat utilizes the existing database schema without requiring new tables or migrations:

1. **`code_chunks`:**
   - Stores file paths, content spans, chunk line boundaries (`start_line`, `end_line`), and 768-dimensional embeddings (`vector(768)`).
   - Reused by `search_code` and `read_file_range`.

2. **`code_symbols`:**
   - Stores AST extracted symbols (`name`, `kind`, `signature`, `docstring`, `file_path`, `start_line`, `end_line`).
   - Reused by `get_symbol`.

3. **`symbol_edges`:**
   - Stores dependency and caller relationships (`from_symbol_id`, `to_symbol_id`, `edge_type`).
   - Reused by `find_callers` (`edge_type IN ('calls', 'invokes')`).

4. **`repository_files`:**
   - Stores indexed file tree and file metadata.

---

## 2. Redis Caching & Rate Limiting

- **Query Caching:** Existing Redis client manages query hashes and retrieval cache keys `(repo_id, index_version, query_hash)`.
- **Session Auth:** Redis validates user session tokens without extra database round-trips.
- **Client Reuse:** The agentic orchestrator reuses the shared `app.core.redis.redis_client`; no duplicate Redis connections or pools are created.
