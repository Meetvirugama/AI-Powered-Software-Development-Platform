"""Unit tests for code-aware tokenizer and search text generator."""

from ai.retrieval.code_tokenizer import (
    generate_code_search_text,
    normalize_identifier,
    split_identifier,
    tokenize_code,
)


class TestSplitIdentifier:
    def test_camel_case_splitting(self):
        tokens = split_identifier("getUserById")
        assert "getUserById" in tokens
        assert "get" in tokens
        assert "user" in tokens
        assert "by" in tokens
        assert "id" in tokens
        assert "get_user_by_id" in tokens

    def test_pascal_case_splitting(self):
        tokens = split_identifier("UserAuthenticationService")
        assert "UserAuthenticationService" in tokens
        assert "user" in tokens
        assert "authentication" in tokens
        assert "service" in tokens

    def test_snake_case_splitting(self):
        tokens = split_identifier("get_user_by_id")
        assert "get_user_by_id" in tokens
        assert "get" in tokens
        assert "user" in tokens
        assert "by" in tokens
        assert "id" in tokens

    def test_constants_and_all_caps(self):
        tokens = split_identifier("AUTH_TOKEN_EXPIRED")
        assert "AUTH_TOKEN_EXPIRED" in tokens
        assert "auth" in tokens
        assert "token" in tokens
        assert "expired" in tokens

    def test_acronym_splitting(self):
        tokens = split_identifier("HTTPResponse")
        assert "HTTPResponse" in tokens
        assert "http" in tokens
        assert "response" in tokens

    def test_file_paths(self):
        tokens = split_identifier("src/auth/token-service.py")
        assert "src" in tokens
        assert "auth" in tokens
        assert "token" in tokens
        assert "service" in tokens
        assert "py" in tokens

    def test_numeric_identifiers(self):
        tokens = split_identifier("sha256_hash_v2")
        assert "sha" in tokens
        assert "256" in tokens
        assert "hash" in tokens
        assert "v2" in tokens or "2" in tokens

    def test_empty_and_whitespace(self):
        assert split_identifier("") == []
        assert split_identifier("   ") == []
        assert normalize_identifier(None) == []  # type: ignore

    def test_deduplication(self):
        tokens = split_identifier("UserUserUser")
        assert len([t for t in tokens if t.lower() == "user"]) == 1


class TestTokenizeCode:
    def test_code_block_tokenization(self):
        code = """
        def fetch_user_profile(user_id: str) -> UserProfile:
            cache_key = f"profile:{user_id}"
            return db.query(UserProfile).get(user_id)
        """
        tokens = tokenize_code(code)
        assert "fetch" in [t.lower() for t in tokens]
        assert "user" in [t.lower() for t in tokens]
        assert "profile" in [t.lower() for t in tokens]
        assert "cache" in [t.lower() for t in tokens]


class TestGenerateCodeSearchText:
    def test_generates_search_text_with_symbol_and_path(self):
        search_text = generate_code_search_text(
            content="def calculate_total(items): return sum(items)",
            file_path="src/billing/calculator.py",
            symbol_name="calculate_total",
            symbol_kind="function",
        )
        assert "calculate_total" in search_text
        assert "calculate" in search_text
        assert "total" in search_text
        assert "src/billing/calculator.py" in search_text
        assert "calculator.py" in search_text
        assert "function" in search_text
        assert "sum(items)" in search_text

    def test_empty_content_graceful(self):
        search_text = generate_code_search_text("")
        assert search_text == ""
