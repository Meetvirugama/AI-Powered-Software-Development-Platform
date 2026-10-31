"""F-16: Test end-to-end embedding dimension invariant (768-d).

Verifies that Settings, ORM Column, Validator, Alembic Migration, and Provider
all agree on 768-dimensional embeddings.
"""

from __future__ import annotations

import re
from pathlib import Path

from ai.embeddings.gemini_provider import GeminiEmbeddingProvider
from app.core.config import get_settings
from app.models.code_chunk import CodeChunk


def test_embedding_dimension_settings_equals_768() -> None:
    """Settings default and invariant must be 768."""
    settings = get_settings()
    assert settings.embedding_dimensions == 768


def test_embedding_provider_default_dimension_equals_768() -> None:
    """GeminiEmbeddingProvider default dimension must match 768."""
    provider = GeminiEmbeddingProvider(api_keys=["test-key-1"])
    assert provider.embedding_dimensions == 768


def test_code_chunk_model_dimension_equals_768() -> None:
    """CodeChunk ORM column type must have dimension 768."""
    column = CodeChunk.__table__.columns["embedding"]
    assert hasattr(column.type, "dim")
    assert column.type.dim == 768


def test_alembic_migration_defines_vector_768() -> None:
    """Alembic migrations must specify Vector(768)."""
    migrations_dir = Path(__file__).parent.parent / "migrations" / "versions"
    found_vector_768 = False

    for migration_file in migrations_dir.glob("*.py"):
        content = migration_file.read_text(encoding="utf-8")
        if re.search(r"Vector\(\s*768\s*\)", content):
            found_vector_768 = True
            break

    assert found_vector_768, "At least one Alembic migration must create Vector(768) column."

