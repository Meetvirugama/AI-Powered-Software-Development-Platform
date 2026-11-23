"""Grounding validator tests."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4
import pytest
from ai.schemas.output import RepositoryAnswer
from ai.schemas.output import SourceReference
from ai.schemas.grounding import GroundingResult
from ai.schemas.grounding import GroundingValidator
from types import SimpleNamespace


# Unit tests for Dev Day 3 — GroundingValidator.

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
# Fixture — GroundingValidator with a fake DB session
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo_id():
    return uuid4()


def _make_validator_with_mock_check(grounding_results: list[GroundingResult]) -> GroundingValidator:
    """
    Build a GroundingValidator whose _check_source is mocked to return
    the given GroundingResult objects in order.
    """
    validator = GroundingValidator(db_session=MagicMock())  # non-None db triggers real path
    # Mock the internal _check_source to return our canned results
    call_iter = iter(grounding_results)
    validator._check_source = AsyncMock(side_effect=lambda src, repo_id: next(call_iter))
    return validator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGroundingValidator:

    @pytest.mark.asyncio
    async def test_empty_sources_returned_unchanged(self, repo_id):
        """Answer with no sources passes through without any DB calls."""
        validator = GroundingValidator()  # no db needed
        answer = _answer(sources=[])

        result = await validator.validate_sources(answer, repo_id)

        assert result.answer == answer.answer
        assert result.sources == []
        assert result.confidence == "high"

    @pytest.mark.asyncio
    async def test_all_sources_grounded_kept(self, repo_id):
        """All sources exist and have valid line ranges — all kept, confidence unchanged."""
        src1 = _source("src/auth.py", 1, 20)
        src2 = _source("src/models.py", 5, 30)

        results = [
            GroundingResult(source=src1, grounded=True, reason="ok"),
            GroundingResult(source=src2, grounded=True, reason="ok"),
        ]
        validator = _make_validator_with_mock_check(results)
        answer = _answer([src1, src2], confidence="high")

        result = await validator.validate_sources(answer, repo_id)

        assert len(result.sources) == 2
        assert result.confidence == "high"

    @pytest.mark.asyncio
    async def test_file_not_found_source_removed(self, repo_id):
        """A source citing a non-existent file is removed from the answer."""
        real_src = _source("src/auth.py", 1, 20)
        fake_src = _source("src/does_not_exist.py", 5, 10)

        results = [
            GroundingResult(source=real_src, grounded=True, reason="ok"),
            GroundingResult(source=fake_src, grounded=False, reason="file_not_found"),
        ]
        validator = _make_validator_with_mock_check(results)
        answer = _answer([real_src, fake_src], confidence="high")

        result = await validator.validate_sources(answer, repo_id)

        assert len(result.sources) == 1
        assert result.sources[0].file == "src/auth.py"

    @pytest.mark.asyncio
    async def test_line_range_beyond_file_length_removed(self, repo_id):
        """A source with end_line > file.line_count is removed."""
        valid_src = _source("src/auth.py", 1, 20)
        bad_range_src = _source("src/auth.py", 100, 999)  # file only has 50 lines

        results = [
            GroundingResult(source=valid_src, grounded=True, reason="ok"),
            GroundingResult(source=bad_range_src, grounded=False, reason="line_range_invalid"),
        ]
        validator = _make_validator_with_mock_check(results)
        answer = _answer([valid_src, bad_range_src])

        result = await validator.validate_sources(answer, repo_id)

        assert len(result.sources) == 1
        assert result.sources[0].start_line == 1

    @pytest.mark.asyncio
    async def test_majority_ungrounded_downgrades_confidence_to_low(self, repo_id):
        """More than 50% ungrounded sources → confidence downgraded to 'low'."""
        src1 = _source("real.py")
        src2 = _source("fake1.py")
        src3 = _source("fake2.py")

        results = [
            GroundingResult(source=src1, grounded=True, reason="ok"),
            GroundingResult(source=src2, grounded=False, reason="file_not_found"),
            GroundingResult(source=src3, grounded=False, reason="file_not_found"),
        ]
        validator = _make_validator_with_mock_check(results)
        answer = _answer([src1, src2, src3], confidence="high")

        result = await validator.validate_sources(answer, repo_id)

        assert result.confidence == "low", (
            "Confidence must be downgraded to 'low' when >50% of citations are ungrounded."
        )
        assert len(result.sources) == 1

    @pytest.mark.asyncio
    async def test_minority_ungrounded_keeps_original_confidence(self, repo_id):
        """50% or fewer ungrounded sources → original confidence kept."""
        src1 = _source("real1.py")
        src2 = _source("real2.py")
        src3 = _source("fake.py")

        results = [
            GroundingResult(source=src1, grounded=True, reason="ok"),
            GroundingResult(source=src2, grounded=True, reason="ok"),
            GroundingResult(source=src3, grounded=False, reason="file_not_found"),
        ]
        validator = _make_validator_with_mock_check(results)
        answer = _answer([src1, src2, src3], confidence="medium")

        result = await validator.validate_sources(answer, repo_id)

        # 1/3 ≈ 33% ungrounded — below the 50% threshold
        assert result.confidence == "medium"
        assert len(result.sources) == 2

    @pytest.mark.asyncio
    async def test_original_answer_not_mutated(self, repo_id):
        """validate_sources must return a NEW RepositoryAnswer, not mutate the original."""
        src1 = _source("real.py")
        src2 = _source("fake.py")

        results = [
            GroundingResult(source=src1, grounded=True, reason="ok"),
            GroundingResult(source=src2, grounded=False, reason="file_not_found"),
        ]
        validator = _make_validator_with_mock_check(results)
        answer = _answer([src1, src2], confidence="high")
        original_source_count = len(answer.sources)

        result = await validator.validate_sources(answer, repo_id)

        # Original must not be modified
        assert len(answer.sources) == original_source_count, (
            "validate_sources must not mutate the original RepositoryAnswer."
        )
        assert result is not answer

    @pytest.mark.asyncio
    async def test_all_sources_ungrounded_returns_empty_low(self, repo_id):
        """All sources hallucinated → empty sources list + confidence='low'."""
        src1 = _source("hallucinated1.py")
        src2 = _source("hallucinated2.py")

        results = [
            GroundingResult(source=src1, grounded=False, reason="file_not_found"),
            GroundingResult(source=src2, grounded=False, reason="file_not_found"),
        ]
        validator = _make_validator_with_mock_check(results)
        answer = _answer([src1, src2], confidence="high")

        result = await validator.validate_sources(answer, repo_id)

        assert result.sources == []
        assert result.confidence == "low"


# Unit tests for Dev Day 4 — GroundingValidator DB integration.

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_source(file: str, start: int = 1, end: int = 10, symbol: str | None = None) -> SourceReference:
    return SourceReference(file=file, start_line=start, end_line=end, symbol=symbol)


def _db_answer(sources: list[SourceReference], confidence: str = "high") -> RepositoryAnswer:
    return RepositoryAnswer(
        answer="Authentication is handled in auth.py",
        sources=sources,
        confidence=confidence,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_repo_id():
    return uuid4()


@pytest.fixture()
def grounding_db_session():
    # A fake SQLAlchemy Session
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.repositories.repository_files.get_file_by_path")
async def test_hallucinated_file_is_removed_from_sources(mock_get_file, db_repo_id, grounding_db_session):
    """
    Test Day 4 Check 1:
    If the LLM cites a file that doesn't exist in Om's DB, it is removed.
    """
    # Arrange: The database returns None (file not found)
    mock_get_file.return_value = None

    validator = GroundingValidator(db_session=grounding_db_session)
    hallucinated_source = _db_source("src/auth/fake_file.py")
    answer = _db_answer([hallucinated_source])

    # Act
    result = await validator.validate_sources(answer, db_repo_id)

    # Assert
    assert len(result.sources) == 0  # The fake citation was deleted!
    assert result.confidence == "low"  # 100% of citations were fake, so confidence drops

    # Verify we actually called Om's function
    mock_get_file.assert_called_once_with(
        db=grounding_db_session,
        repository_id=db_repo_id,
        path="src/auth/fake_file.py"
    )

@pytest.mark.asyncio
@patch("app.repositories.repository_files.get_file_by_path")
async def test_hallucinated_line_range_is_removed_from_sources(mock_get_file, db_repo_id, grounding_db_session):
    """
    Test Day 4 Check 2:
    If the LLM cites lines 40-50, but the file only has 35 lines, it is removed.
    """
    # Arrange: The database returns a file with only 35 lines
    mock_get_file.return_value = SimpleNamespace(line_count=35)

    validator = GroundingValidator(db_session=grounding_db_session)

    # The LLM hallucinates that the answer is on lines 40-50
    hallucinated_source = _db_source("src/auth/service.py", start=40, end=50)
    answer = _db_answer([hallucinated_source])

    # Act
    result = await validator.validate_sources(answer, db_repo_id)

    # Assert
    assert len(result.sources) == 0  # The fake citation was deleted!
    assert result.confidence == "low"


@pytest.mark.asyncio
@patch("app.repositories.repository_files.get_file_by_path")
async def test_database_error_fails_closed_and_downgrades(mock_get_file, db_repo_id, grounding_db_session):
    """
    Critical requirement: When database access fails with an exception,
    the citation must NOT be accepted as verified. It must fail closed and downgrade to low.
    """
    mock_get_file.side_effect = RuntimeError("Database connection pool exhausted")
    validator = GroundingValidator(db_session=grounding_db_session)
    source = _db_source("src/auth/service.py", start=1, end=10)
    answer = _db_answer([source], confidence="high")

    result = await validator.validate_sources(answer, db_repo_id)

    assert len(result.sources) == 0, "Unverified citation must be removed when DB access fails"
    assert result.confidence == "low", "Confidence must be downgraded to low on DB failure"


@pytest.mark.asyncio
async def test_no_db_session_fails_closed_and_downgrades(db_repo_id):
    """
    When GroundingValidator is constructed with no DB session, citations cannot
    be verified and must be rejected rather than passed through as verified.
    """
    validator = GroundingValidator(db_session=None)
    source = _db_source("src/auth/service.py", start=1, end=10)
    answer = _db_answer([source], confidence="high")

    result = await validator.validate_sources(answer, db_repo_id)

    assert len(result.sources) == 0, "Citations must not pass through without DB verification"
    assert result.confidence == "low"


@pytest.mark.asyncio
async def test_path_traversal_citation_rejected(db_repo_id, grounding_db_session):
    """Citations containing path traversal ('..') or absolute paths are rejected."""
    validator = GroundingValidator(db_session=grounding_db_session)
    source = _db_source("../../etc/passwd", start=1, end=5)
    answer = _db_answer([source], confidence="high")

    result = await validator.validate_sources(answer, db_repo_id)

    assert len(result.sources) == 0
    assert result.confidence == "low"


@pytest.mark.asyncio
async def test_inverted_line_range_citation_rejected(db_repo_id, grounding_db_session):
    """Citations with start_line > end_line are rejected."""
    validator = GroundingValidator(db_session=grounding_db_session)
    source = _db_source("src/auth/service.py", start=25, end=10)
    answer = _db_answer([source], confidence="high")

    result = await validator.validate_sources(answer, db_repo_id)

    assert len(result.sources) == 0
    assert result.confidence == "low"
