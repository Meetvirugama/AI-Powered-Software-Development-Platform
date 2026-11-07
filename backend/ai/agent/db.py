"""
Database session execution helper for Agent tools.
Enables tools to run queries seamlessly across sync Session, AsyncSession, or sessionmaker.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_db_query(db: Any, stmt: Any, scalar_one: bool = False) -> Any:
    """
    Execute a SQLAlchemy statement against any provided DB handle.

    Supports:
    - Async sessionmaker (e.g. ``AsyncSessionLocal``)
    - Active ``AsyncSession``
    - Sync sessionmaker (e.g. ``SessionLocal``)
    - Active sync ``Session``
    """
    if db is None:
        return None if scalar_one else []

    # Case 1: Callable sessionmaker
    if callable(db) and not hasattr(db, "execute"):
        session_factory = db
        # Check if it's an async context manager or sync
        try:
            candidate = session_factory()
            if hasattr(candidate, "__aenter__"):
                async with candidate as s:
                    res = await s.execute(stmt)
                    scalars = getattr(res, "scalars", None)
                    if callable(scalars):
                        return scalars().first() if scalar_one else list(scalars().all())
                    if scalar_one:
                        return getattr(res, "scalar_one_or_none", lambda: None)()
                    return list(getattr(res, "all", list)())
            elif hasattr(candidate, "__enter__"):
                with candidate as s:
                    res = s.execute(stmt)
                    scalars = getattr(res, "scalars", None)
                    if callable(scalars):
                        return scalars().first() if scalar_one else list(scalars().all())
                    if scalar_one:
                        return getattr(res, "scalar_one_or_none", lambda: None)()
                    return list(getattr(res, "all", list)())
        except (TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("candidate_session_execution_fallback", extra={"error": str(exc)})

    # Case 2: Active session instance
    if hasattr(db, "execute"):
        execute_fn = db.execute
        if inspect.iscoroutinefunction(execute_fn):
            res = await db.execute(stmt)
        else:
            res = await asyncio.to_thread(db.execute, stmt)

        scalars = getattr(res, "scalars", None)
        if callable(scalars):
            return scalars().first() if scalar_one else list(scalars().all())
        if scalar_one:
            return getattr(res, "scalar_one_or_none", lambda: None)()
        return list(getattr(res, "all", list)())

    return None if scalar_one else []
