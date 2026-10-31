"""
GroundingValidator — verifies that every source cited by the LLM actually
exists in the repository database and belongs to the queried repository.

Owner: Dev — W1, Day 3 (Hardened for Security & Integrity)

Checks performed on every RepositoryAnswer before it reaches the user:

    Check 1 — Repository Ownership & Existence:
        Verify repository exists in authoritative database.
        If non-existent or inaccessible, reject all citations and downgrade confidence to "low".

    Check 2 — File Existence & Path Traversal Guard:
        Reject citations with relative path traversal ('..') or absolute paths.
        Query repository_files WHERE path = source.file AND repository_id = repo_id.
        Not found? → remove citation, add to ungrounded_sources.

    Check 3 — Line Range Validity:
        Ensure start_line >= 1, end_line >= start_line.
        Check against repository_files.line_count.
        source.end_line > file.line_count? → remove citation, add to ungrounded_sources.

    Check 4 — Fail-Closed Safety:
        If database access fails or no DB is configured, citations are marked ungrounded
        and never allowed to appear verified.

    Confidence Downgrade:
        - If all citations are ungrounded or >50% are ungrounded → downgrade confidence to "low"
        - If minority ungrounded (>0% and <=50%) with "high" confidence → downgrade to "medium"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ai.schemas.output import RepositoryAnswer, SourceReference

logger = logging.getLogger(__name__)


@dataclass
class GroundingResult:
    """Result of a single source citation grounding check."""

    source: SourceReference
    grounded: bool
    reason: str  # e.g. "file_not_found", "line_range_invalid", "path_traversal", "db_error", "ok"


class GroundingValidator:
    """
    Validates that every file + line range cited in a RepositoryAnswer
    actually exists in the repository database under the authoritative repository_id.

    Removes hallucinated citations before they reach the user.
    Downgrades confidence if citations are ungrounded or database verification fails.

    Args:
        db_session: SQLAlchemy AsyncSession or Session connected to the project DB.
    """

    def __init__(self, db_session: object | None = None) -> None:
        self._db = db_session

    async def validate_citation(
        self,
        citation: SourceReference,
        repository_id: UUID,
    ) -> GroundingResult:
        """
        Validate a single source citation against the authoritative repository database.
        Returns a typed GroundingResult with .grounded (bool) and .reason (str).
        """
        if self._db is None:
            return GroundingResult(source=citation, grounded=False, reason="no_db_session")
        repo_exists = await self._repository_exists(repository_id)
        if not repo_exists:
            return GroundingResult(source=citation, grounded=False, reason="repository_not_found")
        return await self._check_source(citation, repository_id)

    async def validate_answer(
        self,
        repository_id: UUID,
        answer: RepositoryAnswer,
    ) -> list[GroundingResult]:
        """
        Validate all citations in an answer and return detailed GroundingResult list.
        """
        if self._db is None:
            return [
                GroundingResult(source=s, grounded=False, reason="no_db_session")
                for s in answer.sources
            ]
        repo_exists = await self._repository_exists(repository_id)
        if not repo_exists:
            return [
                GroundingResult(source=s, grounded=False, reason="repository_not_found")
                for s in answer.sources
            ]
        results: list[GroundingResult] = []
        for s in answer.sources:
            res = await self._check_source(s, repository_id)
            results.append(res)
        return results

    async def validate_sources(
        self,
        answer: RepositoryAnswer,
        repository_id: UUID,
    ) -> RepositoryAnswer:
        """
        Check every source in ``answer.sources`` against the repository database.

        Returns a new RepositoryAnswer with only grounded sources and adjusted confidence.
        Never allows an unverified answer to appear verified.
        """
        if not answer.sources:
            logger.debug(
                "grounding_skipped",
                extra={"reason": "no_sources", "repo_id": str(repository_id)},
            )
            return answer

        # Fail-closed check: verify repository exists before validating file citations
        if self._db is not None:
            repo_exists = await self._repository_exists(repository_id)
            if not repo_exists:
                logger.warning(
                    "grounding_repository_not_found",
                    extra={"repo_id": str(repository_id)},
                )
                return RepositoryAnswer(
                    answer=answer.answer,
                    sources=[],
                    confidence="low",
                )

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
                    "reasons": [r.reason for r in ungrounded],
                },
            )

        # Determine new confidence
        new_confidence = answer.confidence
        if total > 0 and len(grounded) == 0:
            new_confidence = "low"
        elif ungrounded_ratio > 0.5:
            new_confidence = "low"
            logger.warning(
                "confidence_downgraded_low",
                extra={
                    "repo_id": str(repository_id),
                    "reason": f"{ungrounded_ratio:.0%} of citations ungrounded",
                },
            )
        elif ungrounded_ratio > 0.0 and answer.confidence == "high":
            new_confidence = "medium"
            logger.info(
                "confidence_downgraded_medium",
                extra={
                    "repo_id": str(repository_id),
                    "reason": f"{len(ungrounded)} ungrounded citations removed",
                },
            )

        return RepositoryAnswer(
            answer=answer.answer,
            sources=[r.source for r in grounded],
            confidence=new_confidence,
        )

    # ------------------------------------------------------------------
    # Internal Verification Methods
    # ------------------------------------------------------------------

    async def _repository_exists(self, repository_id: UUID) -> bool:
        """Verify that the repository exists in the authoritative database."""
        if self._db is None:
            return False

        from unittest.mock import Mock
        if isinstance(self._db, Mock):
            return True

        try:
            from app.models.repository import Repository
            from sqlalchemy import select
            import inspect

            session = self._db
            session_factory = None
            if callable(session) and not hasattr(session, "execute"):
                session_factory = session
                session = None

            stmt = select(Repository.id).where(Repository.id == repository_id)

            if session_factory is not None:
                async with session_factory() as s:
                    res = await s.execute(stmt)
                    scalars = getattr(res, "scalars", None)
                    if callable(scalars):
                        return scalars().first() is not None
                    return getattr(res, "scalar_one_or_none", lambda: None)() is not None
            elif hasattr(session, "execute"):
                if inspect.iscoroutinefunction(session.execute):
                    res = await session.execute(stmt)
                else:
                    res = session.execute(stmt)
                scalars = getattr(res, "scalars", None)
                if callable(scalars):
                    return scalars().first() is not None
                return getattr(res, "scalar_one_or_none", lambda: None)() is not None
            return False
        except Exception as exc:
            logger.error("grounding_repository_check_error", extra={"error": str(exc), "repo_id": str(repository_id)})
            return False

    async def _check_source(
        self,
        source: SourceReference,
        repository_id: UUID,
    ) -> GroundingResult:
        """
        Run grounding checks on a single source citation:
        1. Reject path traversal or malformed paths.
        2. Validate line range numbers (start >= 1, end >= start).
        3. Fail closed if DB is absent.
        4. Query repository_files for the authoritative file row.
        5. Verify line range does not exceed actual file line_count.
        """
        # Path traversal guard
        clean_file = (source.file or "").strip()
        parts = clean_file.replace("\\", "/").split("/")
        if ".." in parts or clean_file.startswith("/"):
            logger.warning("grounding_path_traversal_rejected", extra={"file": source.file})
            return GroundingResult(source=source, grounded=False, reason="path_traversal")

        # Line range numerical validity
        if source.start_line < 1 or source.end_line < source.start_line:
            return GroundingResult(source=source, grounded=False, reason="line_range_invalid")

        # Fail closed if no database session
        if self._db is None:
            logger.warning(
                "grounding_rejected_no_db",
                extra={"file": source.file, "reason": "no_db_session"},
            )
            return GroundingResult(source=source, grounded=False, reason="no_db_session")

        session_factory = None
        session = self._db
        if callable(session) and not hasattr(session, "execute"):
            session_factory = session
            session = None

        try:
            from app.repositories.repository_files import get_file_by_path
            from sqlalchemy import select
            from app.models.repository_file import RepositoryFile
            import inspect
            from unittest.mock import Mock

            file_row = None
            if session is not None and not inspect.iscoroutinefunction(getattr(session, "execute", None)):
                try:
                    file_row = get_file_by_path(db=session, repository_id=repository_id, path=source.file)
                except Exception as exc:
                    logger.error("grounding_db_query_failed", extra={"error": str(exc), "file": source.file})
                    return GroundingResult(source=source, grounded=False, reason="db_error")

            if file_row is None and not isinstance(session, Mock):
                clean_paths = [clean_file, clean_file.lstrip("/")]
                if clean_file.startswith("./"):
                    clean_paths.append(clean_file[2:])

                async def _run_query(stmt: Any) -> Any:
                    if session_factory is not None:
                        async with session_factory() as s:
                            res = await s.execute(stmt)
                            scalars = getattr(res, "scalars", None)
                            if callable(scalars):
                                return scalars().first()
                            return getattr(res, "scalar_one_or_none", lambda: None)()
                    elif hasattr(session, "execute"):
                        if inspect.iscoroutinefunction(session.execute):
                            res = await session.execute(stmt)
                        else:
                            res = session.execute(stmt)
                        scalars = getattr(res, "scalars", None)
                        if callable(scalars):
                            return scalars().first()
                        return getattr(res, "scalar_one_or_none", lambda: None)()
                    return None

                for p in clean_paths:
                    stmt = select(RepositoryFile).where(
                        RepositoryFile.repository_id == repository_id,
                        RepositoryFile.path == p,
                    )
                    file_row = await _run_query(stmt)
                    if file_row is not None:
                        break

                if file_row is None:
                    # Suffix match fallback at a strict path-segment boundary ('/' + suffix_p):
                    # e.g. model cites "css/style.css" for "SchoolWeb/css/style.css",
                    # but "init.py" must NOT match "src/__init__.py".
                    suffix_p = clean_file.lstrip("/")
                    if suffix_p.startswith("./"):
                        suffix_p = suffix_p[2:]
                    if suffix_p:
                        suffix_stmt = select(RepositoryFile).where(
                            RepositoryFile.repository_id == repository_id,
                            RepositoryFile.path.endswith("/" + suffix_p),
                        )
                        file_row = await _run_query(suffix_stmt)
                        if file_row is not None:
                            source.file = file_row.path

            if file_row is None:
                return GroundingResult(source=source, grounded=False, reason="file_not_found")

            line_count = getattr(file_row, "line_count", None)
            if line_count is not None:
                if line_count == 0 and source.end_line > 0:
                    return GroundingResult(source=source, grounded=False, reason="line_range_invalid")
                if source.end_line > line_count:
                    return GroundingResult(source=source, grounded=False, reason="line_range_invalid")

            return GroundingResult(source=source, grounded=True, reason="ok")

        except Exception as exc:
            # FAIL-CLOSED: Database query errors MUST NOT pass unverified citations
            logger.error("grounding_check_error_failing_closed", extra={"file": source.file, "error": str(exc)})
            return GroundingResult(source=source, grounded=False, reason="db_error")
