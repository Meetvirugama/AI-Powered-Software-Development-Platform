"""
GroundingValidator — verifies that every source cited by the LLM actually
exists in the repository database.

Owner: Dev — W1, Day 3

Checks performed on every RepositoryAnswer before it reaches the user:

    Check 1 — File existence:
        Query repository_files WHERE path = source.file AND repository_id = repo_id
        Not found? → remove citation, add to ungrounded_sources

    Check 2 — Line range validity:
        Query repository_files.line_count
        source.end_line > file.line_count? → remove citation, add to ungrounded_sources

    Confidence downgrade:
        If > 50% of citations are ungrounded → downgrade confidence to "low"

Usage (Day 4+ when Om's repository layer is available)::

    validator = GroundingValidator(db_session=session)
    validated_answer = await validator.validate_sources(answer, repository_id)
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from ai.schemas.output import RepositoryAnswer, SourceReference

if TYPE_CHECKING:
    pass  # DB session type added when Om's layer is available

logger = logging.getLogger(__name__)


@dataclass
class GroundingResult:
    """Result of a single source citation grounding check."""

    source: SourceReference
    grounded: bool
    reason: str  # e.g. "file_not_found", "line_range_invalid", "ok"


class GroundingValidator:
    """
    Validates that every file + line range cited in a RepositoryAnswer
    actually exists in the repository database.

    Removes hallucinated citations before they reach the user.
    Downgrades confidence if > 50% of citations are ungrounded.

    Args:
        db_session: SQLAlchemy AsyncSession connected to the project DB.
                    Injected at construction time (Om's repository layer).

    Note:
        The DB session is optional for the Day 3 skeleton — the public
        interface is final, but the DB calls are stubbed until Om's
        repository layer is available.
    """

    def __init__(self, db_session: object | None = None) -> None:
        self._db = db_session

    async def validate_sources(
        self,
        answer: RepositoryAnswer,
        repository_id: UUID,
    ) -> RepositoryAnswer:
        """
        Check every source in ``answer.sources`` against the repository database.

        Algorithm:
        1. For each source, call ``_check_source(source, repository_id)``.
        2. Collect grounded and ungrounded results separately.
        3. If > 50% ungrounded → downgrade confidence to "low".
        4. Return a new RepositoryAnswer with only grounded sources.

        Args:
            answer:        The raw RepositoryAnswer from the LLM (unvalidated).
            repository_id: UUID of the repository being queried.

        Returns:
            A new RepositoryAnswer with hallucinated citations removed and
            confidence adjusted if necessary.
        """
        if not answer.sources:
            logger.debug(
                "grounding_skipped",
                extra={"reason": "no_sources", "repo_id": str(repository_id)},
            )
            return answer

        results: list[GroundingResult] = []
        for source in answer.sources:
            result = await self._check_source(source, repository_id)
            results.append(result)

        grounded = [r for r in results if r.grounded]
        ungrounded = [r for r in results if not r.grounded]

        total = len(results)
        ungrounded_ratio = len(ungrounded) / total if total > 0 else 0.0

        logger.info(
            "grounding_complete",
            extra={
                "repo_id": str(repository_id),
                "total_sources": total,
                "grounded": len(grounded),
                "ungrounded": len(ungrounded),
                "ungrounded_ratio": round(ungrounded_ratio, 2),
            },
        )

        if ungrounded:
            logger.warning(
                "ungrounded_sources_removed",
                extra={
                    "repo_id": str(repository_id),
                    "ungrounded_files": [r.source.file for r in ungrounded],
                },
            )

        # Determine new confidence
        new_confidence = answer.confidence
        if ungrounded_ratio > 0.5:
            new_confidence = "low"
            logger.warning(
                "confidence_downgraded",
                extra={
                    "repo_id": str(repository_id),
                    "reason": f"{ungrounded_ratio:.0%} of citations ungrounded",
                },
            )

        return RepositoryAnswer(
            answer=answer.answer,
            sources=[r.source for r in grounded],
            confidence=new_confidence,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _check_source(
        self,
        source: SourceReference,
        repository_id: UUID,
    ) -> GroundingResult:
        """
        Run both grounding checks on a single source citation.

        Check 1: Does the file exist in repository_files?
        Check 2: Is the line range within the file's line_count?

        Returns:
            GroundingResult with grounded=True if both checks pass.

        Note:
            Day 3 stub — DB query stubbed. Full implementation in Day 4
            once Om's repository layer (get_file_by_path) is available.
        """
        if self._db is None:
            # Stub: when no DB is provided, treat all sources as grounded.
            # Replace with real query when Om's repository layer is available.
            logger.debug(
                "grounding_stubbed",
                extra={"file": source.file, "reason": "no_db_session"},
            )
            return GroundingResult(source=source, grounded=True, reason="stub_no_db")

        # Day 4 implementation:
        # from app.repositories.repository_files import get_file_by_path
        #
        # file_row = await get_file_by_path(
        #     db=self._db,
        #     repository_id=repository_id,
        #     path=source.file,
        # )
        #
        # if file_row is None:
        #     return GroundingResult(source=source, grounded=False, reason="file_not_found")
        #
        # if source.end_line > file_row.line_count:
        #     return GroundingResult(source=source, grounded=False, reason="line_range_invalid")
        #
        # return GroundingResult(source=source, grounded=True, reason="ok")

        raise NotImplementedError(
            "GroundingValidator._check_source() DB path implemented on Day 4 "
            "once Om's repository_files query layer is available."
        )
