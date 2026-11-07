# Code-Aware Lexical Search

## 1. Problem Statement

Standard PostgreSQL English full-text search dictionaries strip symbols, apply English stemming, and treat concatenated programming identifiers like `getUserById` or `JWTMiddleware` as single unrecognized words. Searching for `get_user` or `user` fails to match `getUserById` when using English stemmers alone.

## 2. Solution: Code Tokenizer & Search Text

The `code_tokenizer` module (`backend/ai/retrieval/code_tokenizer.py`) decomposes code symbols and identifiers:

- **CamelCase / PascalCase**: `getUserById` $\to$ `getUserById`, `get`, `user`, `by`, `id`
- **Acronyms**: `JWTMiddleware` $\to$ `JWTMiddleware`, `jwt`, `middleware`
- **snake_case / kebab-case**: `validate_user_token` $\to$ `validate_user_token`, `validate`, `user`, `token`
- **File Paths**: `src/auth/login.py` $\to$ `src/auth/login.py`, `src`, `auth`, `login`, `py`

### Generated Column & Index

`code_chunks` contains a dedicated `code_search_text` column indexed with a simple GIN index:

```sql
CREATE INDEX ix_code_chunks_code_search_gin ON code_chunks
USING gin (to_tsvector('simple', COALESCE(code_search_text, content)));
```

### Retrieval Query Matching

The lexical search SQL combines:
1. Exact simple tsvector matching on code search text with a $3.0\times$ boost.
2. Exact simple tsvector matching on raw content with a $2.0\times$ boost.
3. Natural-language English tsvector matching with a $1.0\times$ fallback weight.

This guarantees instant, high-precision retrieval for symbol searches while preserving natural language search over comments and docstrings.
