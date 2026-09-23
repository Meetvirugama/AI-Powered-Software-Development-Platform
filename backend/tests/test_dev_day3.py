"""
Unit tests for Dev Day 3 — GroundingValidator.
Owner: Dev — W1

Tests:
    1. test_all_sources_grounded          — all sources found in DB → all kept, confidence unchanged
    2. test_file_not_found_removed        — file not in DB → source removed from answer
    3. test_line_range_invalid_removed    — line range beyond file length → source removed
    4. test_empty_sources_returned_as_is  — answer with no sources returned unchanged
    5. test_majority_ungrounded_downgrades_confidence — >50% ungrounded → confidence="low"
    6. test_minority_ungrounded_keeps_confidence      — ≤50% ungrounded → original confidence kept
    7. test_returns_new_answer_object     — original answer is not mutated

Run with:
    pytest backend/tests/test_dev_day3.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai.schemas.output import RepositoryAnswer, SourceReference
from ai.schemas.grounding import GroundingResult, GroundingValidator


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
