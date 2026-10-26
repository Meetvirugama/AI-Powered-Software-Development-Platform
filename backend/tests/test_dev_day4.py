"""
Unit tests for Dev Day 4 — GroundingValidator DB integration.
Owner: Dev — W1

Tests:
    1. test_hallucinated_file_is_removed_from_sources

Run with:
    pytest backend/tests/test_dev_day4.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ai.schemas.output import RepositoryAnswer, SourceReference
from ai.schemas.grounding import GroundingValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source(file: str, start: int = 1, end: int = 10, symbol: str | None = None) -> SourceReference:
    return SourceReference(file=file, start_line=start, end_line=end, symbol=symbol)


def _answer(sources: list[SourceReference], confidence: str = "high") -> RepositoryAnswer:
    return RepositoryAnswer(
        answer="Authentication is handled in auth.py",
        sources=sources,
        confidence=confidence,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo_id():
    return uuid4()


@pytest.fixture()
def db_session():
    # A fake SQLAlchemy Session
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.repositories.repository_files.get_file_by_path")
async def test_hallucinated_file_is_removed_from_sources(mock_get_file, repo_id, db_session):
    """
    Test Day 4 Check 1:
    If the LLM cites a file that doesn't exist in Om's DB, it is removed.
    """
    # Arrange: The database returns None (file not found)
    mock_get_file.return_value = None
    
    validator = GroundingValidator(db_session=db_session)
    hallucinated_source = _source("src/auth/fake_file.py")
    answer = _answer([hallucinated_source])
    
    # Act
    result = await validator.validate_sources(answer, repo_id)
    
    # Assert
    assert len(result.sources) == 0  # The fake citation was deleted!
    assert result.confidence == "low"  # 100% of citations were fake, so confidence drops
    
    # Verify we actually called Om's function
    mock_get_file.assert_called_once_with(
        db=db_session,
        repository_id=repo_id,
        path="src/auth/fake_file.py"
    )

@pytest.mark.asyncio
@patch("app.repositories.repository_files.get_file_by_path")
async def test_hallucinated_line_range_is_removed_from_sources(mock_get_file, repo_id, db_session):
    """
    Test Day 4 Check 2:
    If the LLM cites lines 40-50, but the file only has 35 lines, it is removed.
    """
    # Arrange: The database returns a file with only 35 lines
    mock_get_file.return_value = SimpleNamespace(line_count=35)
    
    validator = GroundingValidator(db_session=db_session)
    
    # The LLM hallucinates that the answer is on lines 40-50
    hallucinated_source = _source("src/auth/service.py", start=40, end=50)
    answer = _answer([hallucinated_source])
    
    # Act
    result = await validator.validate_sources(answer, repo_id)
    
    # Assert
    assert len(result.sources) == 0  # The fake citation was deleted!
    assert result.confidence == "low"


@pytest.mark.asyncio
@patch("app.repositories.repository_files.get_file_by_path")
async def test_database_error_fails_closed_and_downgrades(mock_get_file, repo_id, db_session):
    """
    Critical requirement: When database access fails with an exception,
    the citation must NOT be accepted as verified. It must fail closed and downgrade to low.
    """
    mock_get_file.side_effect = RuntimeError("Database connection pool exhausted")
    validator = GroundingValidator(db_session=db_session)
    source = _source("src/auth/service.py", start=1, end=10)
    answer = _answer([source], confidence="high")

    result = await validator.validate_sources(answer, repo_id)

    assert len(result.sources) == 0, "Unverified citation must be removed when DB access fails"
    assert result.confidence == "low", "Confidence must be downgraded to low on DB failure"


@pytest.mark.asyncio
async def test_no_db_session_fails_closed_and_downgrades(repo_id):
    """
    When GroundingValidator is constructed with no DB session, citations cannot
    be verified and must be rejected rather than passed through as verified.
    """
    validator = GroundingValidator(db_session=None)
    source = _source("src/auth/service.py", start=1, end=10)
    answer = _answer([source], confidence="high")

    result = await validator.validate_sources(answer, repo_id)

    assert len(result.sources) == 0, "Citations must not pass through without DB verification"
    assert result.confidence == "low"


@pytest.mark.asyncio
async def test_path_traversal_citation_rejected(repo_id, db_session):
    """Citations containing path traversal ('..') or absolute paths are rejected."""
    validator = GroundingValidator(db_session=db_session)
    source = _source("../../etc/passwd", start=1, end=5)
    answer = _answer([source], confidence="high")

    result = await validator.validate_sources(answer, repo_id)

    assert len(result.sources) == 0
    assert result.confidence == "low"


@pytest.mark.asyncio
async def test_inverted_line_range_citation_rejected(repo_id, db_session):
    """Citations with start_line > end_line are rejected."""
    validator = GroundingValidator(db_session=db_session)
    source = _source("src/auth/service.py", start=25, end=10)
    answer = _answer([source], confidence="high")

    result = await validator.validate_sources(answer, repo_id)

    assert len(result.sources) == 0
    assert result.confidence == "low"

