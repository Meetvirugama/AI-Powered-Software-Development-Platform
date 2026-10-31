"""
Base history service providing unified session management and database session lifecycles.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class BaseHistoryService:
    """Base history service managing session lifecycle across all intelligence history services."""

    def __init__(
        self,
        session_factory: Optional[sessionmaker] = None,
        session: Optional[Session] = None,
    ) -> None:
        self.session_factory = session_factory
        self._session = session

    @contextmanager
    def _get_session(self, db: Optional[Session] = None) -> Generator[Session, None, None]:
        """Provide an active database session from argument, cached session, or session factory."""
        if db is not None:
            yield db
            return
        if self._session is not None:
            yield self._session
            return
        if self.session_factory is not None:
            s: Session = self.session_factory()
            try:
                yield s
            finally:
                s.close()
            return
        raise RuntimeError(f"No database session or session_factory configured for {self.__class__.__name__}.")

